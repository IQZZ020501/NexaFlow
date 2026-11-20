"""Fixed provider endpoints; credentials and provider errors stay server-side."""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import quote, urlencode

import httpx2

from app.adapters.integrations.tencent import READ_ONLY_POST_OPERATIONS, build_request
from app.adapters.integrations.validation import resource_identifier as _identifier
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
    elif provider == "feishu":
        endpoint = "https://open.feishu.cn/open-apis/authen/v1/authorize"
        query.update(
            code_challenge=base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            )
            .rstrip(b"=")
            .decode(),
            code_challenge_method="S256",
        )
    else:
        raise IntegrationProviderError("Unsupported integration provider.")
    return endpoint + "?" + urlencode(query)


async def exchange_tokens(provider, client_id, client_secret, **values):
    headers = {"Accept": "application/json"}
    if provider == "dida":
        encoded = base64.b64encode(
            f"{quote(client_id, safe='')}:{quote(client_secret, safe='')}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {encoded}"
        values.pop("code_verifier", None)
        url = "https://dida365.com/oauth/token"
    elif provider == "feishu":
        values.update(client_id=client_id, client_secret=client_secret)
        url = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
    else:
        raise IntegrationProviderError("Unsupported integration provider.")
    result = await _request(
        "POST",
        url,
        headers=headers,
        **({"body": values} if provider == "feishu" else {"data": values}),
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


async def call_integration(provider, operation, arguments, credentials, request_id):
    headers = {"Authorization": f"Bearer {credentials['access_token']}"}
    method, body, query = "GET", None, {}
    if provider == "dida":
        base = "https://api.dida365.com/open/v1"
        if operation == "list_projects":
            path = "/project"
        elif operation == "list_tasks":
            path = f"/project/{_identifier(arguments['project_id'])}/data"
        elif operation == "create_task":
            method, path = "POST", "/task"
            body = {
                "projectId": _identifier(arguments["project_id"]),
                "title": arguments["title"],
                "content": arguments.get("content", ""),
            }
            if arguments.get("due_date"):
                body.update(
                    dueDate=arguments["due_date"],
                    timeZone=arguments.get("time_zone", "Asia/Shanghai"),
                )
        elif operation == "complete_task":
            method = "POST"
            path = f"/project/{_identifier(arguments['project_id'])}/task/{_identifier(arguments['task_id'])}/complete"
        else:
            raise IntegrationProviderError("Unsupported integration operation.")
    elif provider == "feishu":
        base = "https://open.feishu.cn/open-apis"
        if operation == "read_document":
            path = f"/docx/v1/documents/{_identifier(arguments['document_id'])}/raw_content"
        elif operation == "send_message":
            method, path = "POST", "/im/v1/messages"
            query = {"receive_id_type": "open_id"}
            body = {
                "receive_id": _identifier(arguments["open_id"]),
                "msg_type": "text",
                "content": json.dumps({"text": arguments["text"]}, ensure_ascii=False),
                "uuid": hashlib.sha256(request_id.encode()).hexdigest()[:32],
            }
        else:
            raise IntegrationProviderError("Unsupported integration operation.")
    elif provider == "tencent_meeting":
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
    if isinstance(result, dict) and (
        result.get("error_info") or provider == "feishu" and result.get("code", 0) != 0
    ):
        raise IntegrationProviderError(
            "Integration request failed. Check the account authorization and application permissions."
        )
    return result
