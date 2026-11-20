"""Fixed provider endpoints; credentials and provider errors stay server-side."""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import httpx2

from app.adapters.integrations import dida, feishu
from app.adapters.integrations.tencent import READ_ONLY_POST_OPERATIONS, build_request
from app.adapters.mcp.client import (
    _hardened_http_client_factory,
    validate_mcp_destination,
)
from app.ports.integrations import IntegrationProviderError
from app.ports.mcp import McpClientError

_LIMIT = 2 * 1024 * 1024


async def _request(
    method,
    url,
    *,
    headers=None,
    data=None,
    body=None,
    limit=_LIMIT,
    provider=None,
    side_effecting=None,
    oauth_pending=False,
):
    writing = method != "GET" if side_effecting is None else side_effecting
    try:
        destination = await validate_mcp_destination(url, False)
        async with _hardened_http_client_factory(
            destination=destination, timeout=httpx2.Timeout(15)
        ) as client:
            async with client.stream(
                method, url, headers=headers or {}, data=data, json=body
            ) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > limit:
                        raise IntegrationProviderError(
                            "Integration response exceeds its limit.", uncertain=writing
                        )
                try:
                    result = json.loads(raw) if raw else {}
                except ValueError:
                    result = None
                error_info = (
                    result.get("error_info") if isinstance(result, dict) else None
                )
                if (
                    oauth_pending
                    and response.status_code in (200, 400)
                    and isinstance(result, dict)
                ):
                    return result
                if (
                    provider == "feishu"
                    and isinstance(result, dict)
                    and result.get("code") in (99991663, 99991668, 99991677)
                ):
                    raise IntegrationProviderError(
                        "Integration authorization expired. Please install again.",
                        unauthorized=True,
                    )
                if (
                    provider == "tencent_meeting"
                    and isinstance(error_info, dict)
                    and (
                        error_info.get("new_error_code") == 200190303
                        or error_info.get("error_code") == 190303
                    )
                ):
                    raise IntegrationProviderError(
                        "Integration authorization expired. Please install again.",
                        unauthorized=True,
                    )
                if not 200 <= response.status_code < 300:
                    raise IntegrationProviderError(
                        "Integration request failed. Check the account authorization and application permissions.",
                        uncertain=writing and response.status_code >= 500,
                        unauthorized=response.status_code == 401,
                    )
                if not isinstance(result, (dict, list)):
                    raise ValueError()
                return result
    except IntegrationProviderError:
        raise
    except McpClientError as exc:
        raise IntegrationProviderError(
            "Integration service could not be reached."
        ) from exc
    except (httpx2.ConnectError, httpx2.ConnectTimeout) as exc:
        raise IntegrationProviderError(
            "Integration service could not be reached."
        ) from exc
    except Exception as exc:
        raise IntegrationProviderError(
            "Integration response was unavailable.", uncertain=writing
        ) from exc


def authorization_url(provider, client_id, redirect_uri, state, verifier, scopes):
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "scope": " ".join(scopes),
    }
    if provider == "dida":
        endpoint = "https://dida365.com/oauth/authorize"
    else:
        raise IntegrationProviderError("Unsupported integration provider.")
    query.update(
        code_challenge=base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        )
        .rstrip(b"=")
        .decode(),
        code_challenge_method="S256",
    )
    return endpoint + "?" + urlencode(query)


async def register_public_client(provider, redirect_uri, scopes):
    if provider != "dida":
        raise IntegrationProviderError("Unsupported integration provider.")
    # Published at https://dida365.com/.well-known/oauth-authorization-server.
    result = await _request(
        "POST",
        "https://api.dida365.com/oauth/register",
        body={
            "client_name": "NexaFlow",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": " ".join(scopes),
        },
        limit=64 * 1024,
    )
    client_id = result.get("client_id") if isinstance(result, dict) else None
    if (
        not isinstance(client_id, str)
        or not 1 <= len(client_id) <= 256
        or any(ord(char) <= 32 for char in client_id)
        or result.get("token_endpoint_auth_method") != "none"
        or result.get("redirect_uris") != [redirect_uri]
    ):
        raise IntegrationProviderError(
            "Integration authorization failed. Please authorize again."
        )
    return client_id


async def exchange_tokens(provider, client_id, client_secret, **values):
    headers = {"Accept": "application/json"}
    if provider == "dida":
        if (
            client_secret
            or not values.get("code_verifier")
            or values.get("grant_type") != "authorization_code"
        ):
            raise IntegrationProviderError(
                "Integration authorization failed. Please authorize again."
            )
        values["client_id"] = client_id
        url = "https://api.dida365.com/oauth/token"
    else:
        raise IntegrationProviderError("Unsupported integration provider.")
    result = await _request(
        "POST",
        url,
        headers=headers,
        data=values,
        limit=64 * 1024,
    )
    if (
        not isinstance(result, dict)
        or result.get("error")
        or result.get("code", 0) != 0
    ):
        raise IntegrationProviderError(
            "Integration authorization failed. Please authorize again."
        )
    return result


async def device_authorization(action, credentials):
    paths = {
        "init": "cli-oauth-init",
        "poll": "cli-oauth-poll",
        "refresh": "cli-refresh-token",
    }
    if action not in paths:
        raise IntegrationProviderError("Invalid integration authorization action.")
    response = await _request(
        "POST",
        "https://work.medialab.qq.com/v2/oauth2/oauth/" + paths[action],
        body=credentials,
        limit=64 * 1024,
    )
    if (
        not isinstance(response, dict)
        or response.get("code") != 0
        or not isinstance(response.get("data"), dict)
    ):
        raise IntegrationProviderError(
            "Integration authorization failed. Please authorize again."
        )
    return response["data"]


async def feishu_authorization(action, credentials):
    return await feishu.authorize(action, credentials, _request)


async def call_integration(provider, operation, arguments, credentials, request_id):
    if provider == "dida":
        return await dida.call_integration(operation, arguments, credentials, _request)
    if provider == "feishu":
        return await feishu.call_integration(
            operation, arguments, credentials, request_id, _request
        )
    headers = {"Authorization": f"Bearer {credentials['access_token']}"}
    method, body, query = "GET", None, {}
    if provider == "tencent_meeting":
        base = "https://api.meeting.qq.com"
        headers = {
            "AccessToken": credentials["access_token"],
            "OpenId": credentials["open_id"],
            "X-TC-Timestamp": str(int(time.time())),
            "X-TC-Nonce": str(secrets.randbelow(900000) + 100000),
            # CLI-issued grants require both their source and original device.
            "Tmeet-Open-Source": "CLI",
            "Tmeet-Unique-ID": f"{credentials['open_id']}*{credentials['device_id']}",
        }
        method, path, query, body = build_request(
            operation, arguments, credentials["open_id"]
        )
    else:
        raise IntegrationProviderError("Unsupported integration provider.")
    url = base + path + ("?" + urlencode(query) if query else "")
    result = await _request(
        method,
        url,
        headers=headers,
        body=body,
        provider=provider,
        side_effecting=method != "GET"
        and not (
            provider == "tencent_meeting" and operation in READ_ONLY_POST_OPERATIONS
        ),
    )
    if isinstance(result, dict) and result.get("error_info"):
        raise IntegrationProviderError(
            "Integration request failed. Check the account authorization and application permissions."
        )
    return result
