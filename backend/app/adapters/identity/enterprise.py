import asyncio
import json
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx2
from cryptography.fernet import InvalidToken
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.entities.identity.enterprise import EnterpriseIdentityConnection
from app.infra.config.settings import Settings
from app.infra.security.keyring import application_secret_key
from app.infra.security.secrets import decrypt_secret, encrypt_secret
from app.ports.enterprise_identity import (
    EnterpriseProviderError,
    ExternalPrincipal,
)

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


def _provider_code(payload: dict[str, Any]) -> int | None:
    for key in ("code", "errcode"):
        value = payload.get(key)
        if type(value) is int:
            return value
    return None


def build_authorization_url(
    connection: EnterpriseIdentityConnection,
    redirect_uri: str,
    state: str,
) -> str:
    if connection.provider == "feishu":
        query = {
            "client_id": connection.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
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
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > _MAX_PROVIDER_RESPONSE_BYTES:
                        raise EnterpriseProviderError("Provider response is too large.")
                    body.extend(chunk)
            payload = json.loads(body)
    except EnterpriseProviderError as exc:
        exc.operation = urlsplit(url).path
        raise
    except Exception as exc:
        raise EnterpriseProviderError(
            "Enterprise identity provider request failed.", operation=urlsplit(url).path
        ) from exc
    if not isinstance(payload, dict):
        raise EnterpriseProviderError(
            "Enterprise identity provider returned invalid data."
        )
    provider_code = _provider_code(payload)
    feishu_error = url in {
        _FEISHU_TOKEN_URL,
        _FEISHU_USER_URL,
    } and provider_code not in (None, 0)
    if not 200 <= response.status_code < 300 or feishu_error:
        # Keep only status and numeric codes; provider messages can echo credentials.
        raise EnterpriseProviderError(
            "Enterprise identity provider rejected the request.",
            operation=urlsplit(url).path,
            http_status=response.status_code,
            provider_code=provider_code,
        )
    return payload


def _required_text(
    payload: dict[str, Any], key: str, *, operation: str = "principal"
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise EnterpriseProviderError(
            "Enterprise identity provider response is incomplete.",
            operation=operation,
            missing_field=key,
        )
    return value


async def _wecom_access_token(
    connection: EnterpriseIdentityConnection,
    client_secret: str,
    settings: Settings,
    *,
    rejected_token: str | None = None,
) -> str:
    # Share credentials across connections without putting the secret in a Redis key.
    credential_id = sha256(
        f"{connection.tenant_id}\0{client_secret}".encode()
    ).hexdigest()
    cache_key = f"nexaflow:enterprise-login:wecom-token:{credential_id}"
    secret_key = application_secret_key(settings)
    try:
        async with (
            asyncio.timeout(25),
            Redis.from_url(
                settings.celery_broker_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            ) as cache,
        ):

            async def cached_token() -> str | None:
                encrypted = await cache.get(cache_key)
                if encrypted:
                    try:
                        token = decrypt_secret(encrypted, secret_key)
                    except (InvalidToken, UnicodeDecodeError):
                        return None
                    if token and token != rejected_token:
                        return token
                return None

            cached = await cached_token()
            if cached:
                return cached
            async with cache.lock(
                f"{cache_key}:refresh", timeout=30, blocking_timeout=12
            ):
                # Another instance may have refreshed while this request waited.
                cached = await cached_token()
                if cached:
                    return cached
                payload = await _request_json(
                    "GET",
                    _WECOM_TOKEN_URL,
                    params={
                        "corpid": connection.tenant_id,
                        "corpsecret": client_secret,
                    },
                )
                if payload.get("errcode") not in (None, 0):
                    raise EnterpriseProviderError(
                        "WeCom rejected the application credentials.",
                        operation=urlsplit(_WECOM_TOKEN_URL).path,
                        http_status=200,
                        provider_code=_provider_code(payload),
                    )
                token = _required_text(
                    payload,
                    "access_token",
                    operation=urlsplit(_WECOM_TOKEN_URL).path,
                )
                expires_in = payload.get("expires_in")
                if type(expires_in) is not int or expires_in <= 0:
                    raise EnterpriseProviderError(
                        "WeCom token expiration is invalid.",
                        operation=urlsplit(_WECOM_TOKEN_URL).path,
                        http_status=200,
                        missing_field="expires_in",
                    )
                await cache.set(
                    cache_key,
                    encrypt_secret(token, secret_key),
                    ex=max(1, expires_in - 60),
                )
                return token
    except (RedisError, OSError, TimeoutError) as exc:
        raise EnterpriseProviderError(
            "WeCom token cache is unavailable.", operation="wecom-token-cache"
        ) from exc


async def resolve_external_principal(
    connection: EnterpriseIdentityConnection,
    client_secret: str,
    code: str,
    redirect_uri: str,
    *,
    settings: Settings,
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
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        user = await _request_json(
            "GET",
            _FEISHU_USER_URL,
            headers={
                "Authorization": f"Bearer {_required_text(token, 'access_token')}"
            },
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
        access_token = await _wecom_access_token(connection, client_secret, settings)
        user = await _request_json(
            "GET",
            _WECOM_USER_URL,
            params={"access_token": access_token, "code": code},
        )
        if user.get("errcode") in (40014, 42001):
            # Only retry explicit token errors; code failures must never be replayed.
            access_token = await _wecom_access_token(
                connection, client_secret, settings, rejected_token=access_token
            )
            user = await _request_json(
                "GET",
                _WECOM_USER_URL,
                params={"access_token": access_token, "code": code},
            )
        if user.get("errcode") not in (None, 0):
            raise EnterpriseProviderError(
                "WeCom rejected the authorization code.",
                operation=urlsplit(_WECOM_USER_URL).path,
                http_status=200,
                provider_code=_provider_code(user),
            )
        if not isinstance(user.get("userid"), str) or not user["userid"]:
            raise EnterpriseProviderError(
                "WeCom did not return an enterprise member ID.",
                operation=urlsplit(_WECOM_USER_URL).path,
                http_status=200,
                provider_code=_provider_code(user),
                missing_field="userid",
            )
        return ExternalPrincipal(
            subject_id=user["userid"],
            tenant_id=connection.tenant_id,
            display_name="",
        )

    raise EnterpriseProviderError("Unsupported enterprise identity provider.")
