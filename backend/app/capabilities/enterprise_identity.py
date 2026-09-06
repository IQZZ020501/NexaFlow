from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import urlencode

import httpx2

from app.entities.enterprise_identity import EnterpriseIdentityConnection

_FEISHU_AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
_FEISHU_TOKEN_URL = "https://accounts.feishu.cn/oauth/v3/token"
_FEISHU_USER_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"
_DINGTALK_AUTHORIZE_URL = "https://login.dingtalk.com/oauth2/auth"
_DINGTALK_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
_DINGTALK_USER_URL = "https://api.dingtalk.com/v1.0/contact/users/me"
_WECOM_AUTHORIZE_URL = "https://login.work.weixin.qq.com/wwlogin/sso/login"
_WECOM_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
_WECOM_USER_URL = "https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo"
_MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024


class EnterpriseProviderError(Exception):
    pass


@dataclass(frozen=True)
class ExternalPrincipal:
    subject_id: str
    tenant_id: str
    display_name: str
    email: str | None = None


def build_authorization_url(
    connection: EnterpriseIdentityConnection,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    if connection.provider == "feishu":
        query = {
            "client_id": connection.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{_FEISHU_AUTHORIZE_URL}?{urlencode(query)}"
    if connection.provider == "dingtalk":
        query = {
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "client_id": connection.client_id,
            "scope": "openid corpid",
            "state": state,
            "prompt": "consent",
            "corpId": connection.tenant_id,
        }
        return f"{_DINGTALK_AUTHORIZE_URL}?{urlencode(query)}"
    if connection.provider == "wecom":
        query = {
            "login_type": "CorpApp",
            "appid": connection.tenant_id,
            "agentid": connection.agent_id or "",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"{_WECOM_AUTHORIZE_URL}?{urlencode(query)}"
    raise EnterpriseProviderError("Unsupported enterprise identity provider.")


async def _request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        async with httpx2.AsyncClient(
            timeout=10.0,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            async with client.stream(method, url, **kwargs) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > _MAX_PROVIDER_RESPONSE_BYTES:
                        raise EnterpriseProviderError("Provider response is too large.")
                    body.extend(chunk)
            payload = json.loads(body)
    except EnterpriseProviderError:
        raise
    except Exception as exc:
        raise EnterpriseProviderError("Enterprise identity provider request failed.") from exc
    if not isinstance(payload, dict):
        raise EnterpriseProviderError("Enterprise identity provider returned invalid data.")
    return payload


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise EnterpriseProviderError("Enterprise identity provider response is incomplete.")
    return value


async def resolve_external_principal(
    connection: EnterpriseIdentityConnection,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> ExternalPrincipal:
    if connection.provider == "feishu":
        token = await _request_json(
            "POST",
            _FEISHU_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": connection.client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        user = await _request_json(
            "GET",
            _FEISHU_USER_URL,
            headers={"Authorization": f"Bearer {_required_text(token, 'access_token')}"},
        )
        data = user.get("data")
        if not isinstance(data, dict):
            raise EnterpriseProviderError("Feishu user response is incomplete.")
        return ExternalPrincipal(
            subject_id=_required_text(data, "open_id"),
            tenant_id=_required_text(data, "tenant_key"),
            display_name=str(data.get("name") or ""),
            email=data.get("email") if isinstance(data.get("email"), str) else None,
        )

    if connection.provider == "dingtalk":
        token = await _request_json(
            "POST",
            _DINGTALK_TOKEN_URL,
            json={
                "clientId": connection.client_id,
                "clientSecret": client_secret,
                "code": code,
                "grantType": "authorization_code",
            },
        )
        access_token = _required_text(token, "accessToken")
        tenant_id = _required_text(token, "corpId")
        user = await _request_json(
            "GET",
            _DINGTALK_USER_URL,
            headers={"x-acs-dingtalk-access-token": access_token},
        )
        subject = user.get("unionId") or user.get("openId")
        if not isinstance(subject, str) or not subject:
            raise EnterpriseProviderError("DingTalk user response is incomplete.")
        return ExternalPrincipal(
            subject_id=subject,
            tenant_id=tenant_id,
            display_name=str(user.get("nick") or ""),
            email=user.get("email") if isinstance(user.get("email"), str) else None,
        )

    if connection.provider == "wecom":
        token = await _request_json(
            "GET",
            _WECOM_TOKEN_URL,
            params={"corpid": connection.tenant_id, "corpsecret": client_secret},
        )
        if token.get("errcode") not in (None, 0):
            raise EnterpriseProviderError("WeCom rejected the application credentials.")
        user = await _request_json(
            "GET",
            _WECOM_USER_URL,
            params={"access_token": _required_text(token, "access_token"), "code": code},
        )
        if user.get("errcode") not in (None, 0):
            raise EnterpriseProviderError("WeCom rejected the authorization code.")
        return ExternalPrincipal(
            subject_id=_required_text(user, "userid"),
            tenant_id=connection.tenant_id,
            display_name="",
        )

    raise EnterpriseProviderError("Unsupported enterprise identity provider.")
