"""Feishu CLI personal-app/device grants and its pinned, user-only API catalog.

Protocol source: larksuite/cli 1.0.100 (c5fbf1a), internal/auth/.
No CLI config files or application credentials are shared between users.
"""

import asyncio
import base64
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from jsonschema import Draft202012Validator, ValidationError

from app.ports.integrations import IntegrationProviderError

_ENDPOINTS = {
    "feishu": ("https://accounts.feishu.cn", "https://open.feishu.cn"),
    "lark": ("https://accounts.larksuite.com", "https://open.larksuite.com"),
}
_AUTH_ERROR = "Integration authorization failed. Please authorize again."


def _auth_error(reason):
    return IntegrationProviderError(_AUTH_ERROR, reason=reason)


@lru_cache(maxsize=1)
def _catalog_data():
    return json.loads(Path(__file__).with_name("feishu_catalog.json").read_text())


def catalog():
    return _catalog_data()["operations"]


def user_scopes(brand):
    # The CLI publishes current user scopes separately from the legacy
    # alternative scopes still present in its API method metadata.
    return _catalog_data()["user_scopes"][_brand(brand)]


def _secret(value, maximum=8000):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or any(ord(char) <= 32 for char in value)
    ):
        raise _auth_error("invalid_authorization_field")
    return value


def _brand(value):
    if not isinstance(value, str) or value not in _ENDPOINTS:
        raise _auth_error("invalid_brand")
    return value


def _interval(value):
    return max(5, min(60, value)) if type(value) is int else 5


def _authorization(response, values, phase):
    values = {**values, "device_code": _secret(response.get("device_code"))}
    interval = _interval(response.get("interval"))
    values["poll_seconds"] = interval
    if phase == "application":
        code = _secret(response.get("user_code"), 256)
        url = _ENDPOINTS["feishu"][1] + "/page/cli?" + urlencode({"user_code": code})
    else:
        url = response.get("verification_uri_complete") or response.get(
            "verification_uri"
        )
        if not isinstance(url, str) or len(url) > 4096:
            raise _auth_error("invalid_verification_url")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc
            not in {urlsplit(u).netloc for u in _ENDPOINTS[values["brand"]]}
            or parsed.username
            or parsed.password
        ):
            host = parsed.hostname or ""
            official = host.endswith(
                (".feishu.cn", ".larksuite.com", ".larkoffice.com")
            )
            raise _auth_error(
                "invalid_verification_host:" + (host if official else "untrusted")
            )
    expiry = response.get("expire_in", response.get("expires_in", 600))
    if type(expiry) is not int or not 1 <= expiry <= 3600:
        raise _auth_error("invalid_authorization_expiry")
    return {
        "pending": True,
        "credentials": values,
        "authorization": {
            "authorization_url": url,
            "phase": phase,
            "mode": "device",
            "poll_seconds": interval,
            "expires_in": min(expiry, 600),
        },
    }


async def _oauth(request, endpoint, *, data=None, body=None, headers=None):
    result = await request(
        "POST",
        endpoint,
        data=data,
        body=body,
        headers=headers,
        limit=64 * 1024,
        oauth_pending=True,
    )
    if not isinstance(result, dict):
        raise _auth_error("invalid_authorization_response")
    # Feishu includes a nonzero numeric code (e.g. 20094) with a normal
    # authorization_pending response. OAuth status takes precedence here.
    if result.get("error") in ("authorization_pending", "slow_down"):
        return result
    if result.get("code", 0) != 0:
        code = result.get("code")
        raise _auth_error(
            "provider_code:" + (str(code) if type(code) is int else "invalid")
        )
    if result.get("error") not in (None, "authorization_pending", "slow_down"):
        known = {
            "invalid_scope",
            "invalid_client",
            "expired_token",
            "access_denied",
            "invalid_request",
            "unauthorized_client",
            "invalid_grant",
            "unsupported_grant_type",
        }
        error = result.get("error")
        raise _auth_error(
            error
            if isinstance(error, str) and error in known
            else "provider_authorization_error"
        )
    return result


async def authorize(action, credentials, request):
    if action == "start":
        response = await _oauth(
            request,
            _ENDPOINTS["feishu"][0] + "/oauth/v1/app/registration",
            data={
                "action": "begin",
                "archetype": "PersonalAgent",
                "auth_method": "client_secret",
                "request_user_info": "open_id tenant_brand",
            },
        )
        return _authorization(
            response, {"stage": "application", "brand": "feishu"}, "application"
        )
    values = dict(credentials)
    brand = _brand(values.get("brand"))
    accounts = _ENDPOINTS[brand][0]
    if action == "refresh":
        return await _oauth(
            request,
            accounts + "/oauth/v3/token",
            body={
                "grant_type": "refresh_token",
                "refresh_token": _secret(values.get("refresh_token")),
                "client_id": _secret(values.get("client_id"), 256),
                "client_secret": _secret(values.get("client_secret")),
            },
        )
    if action != "poll":
        raise IntegrationProviderError("Invalid integration authorization action.")
    if values.get("stage") == "application":
        for _ in range(2):
            response = await _oauth(
                request,
                _ENDPOINTS[brand][0] + "/oauth/v1/app/registration",
                data={
                    "action": "poll",
                    "device_code": _secret(values.get("device_code")),
                },
            )
            info = response.get("user_info") or {}
            if not isinstance(info, dict):
                raise IntegrationProviderError(_AUTH_ERROR)
            actual = _brand(info.get("tenant_brand", brand))
            if actual != brand:
                if brand != "feishu":
                    raise IntegrationProviderError(_AUTH_ERROR)
                brand = values["brand"] = actual
                continue
            break
        else:
            raise IntegrationProviderError(_AUTH_ERROR)
        if not response.get("client_id") or not response.get("client_secret"):
            return _pending(values, response)
        values = {
            "stage": "login",
            "brand": brand,
            "client_id": _secret(response["client_id"], 256),
            "client_secret": _secret(response["client_secret"]),
        }
        scopes = await asyncio.to_thread(user_scopes, brand)
        basic = base64.b64encode(
            (values["client_id"] + ":" + values["client_secret"]).encode()
        ).decode()
        response = await _oauth(
            request,
            _ENDPOINTS[brand][0] + "/oauth/v1/device_authorization",
            headers={"Authorization": "Basic " + basic},
            data={"client_id": values["client_id"], "scope": " ".join(scopes)},
        )
        return _authorization(response, values, "login")
    if values.get("stage") != "login":
        raise IntegrationProviderError(_AUTH_ERROR)
    response = await _oauth(
        request,
        accounts + "/oauth/v3/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": _secret(values.get("device_code")),
            "client_id": _secret(values.get("client_id"), 256),
            "client_secret": _secret(values.get("client_secret")),
        },
    )
    return _pending(values, response) if response.get("error") else response


def _pending(values, response):
    if response.get("error") == "slow_down":
        values["poll_seconds"] = min(60, values.get("poll_seconds", 5) + 5)
    return {"pending": True, "credentials": values}


def _validate(value, schema):
    try:
        Draft202012Validator(schema).validate(value)
    except ValidationError as exc:
        raise IntegrationProviderError(
            "Invalid integration arguments. Inspect the operation schema before calling it."
        ) from exc


def _path_value(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 1024
        or value in (".", "..")
        or re.search(r"[\x00-\x20\x7f/\\%?#]", value)
    ):
        raise IntegrationProviderError("Invalid integration resource identifier.")
    return quote(value, safe="")


async def call_integration(operation, arguments, credentials, request_id, request):
    definitions = await asyncio.to_thread(catalog)
    if operation == "list_operations":
        query = arguments.get("query", "").casefold()
        domain = arguments.get("domain")
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 30)
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise IntegrationProviderError("Invalid integration arguments.")
        matches = [
            {
                "operation": key,
                "description": value["description"],
                "write": value["write"],
            }
            for key, value in definitions.items()
            if (not domain or key.split(".")[0] == domain)
            and query in (key + " " + value["description"]).casefold()
        ]
        return {
            "operations": matches[offset : offset + limit],
            "total": len(matches),
            "next_offset": offset + limit if offset + limit < len(matches) else None,
            "domains": sorted({key.split(".")[0] for key in definitions}),
        }
    name = arguments.get("operation")
    definition = definitions.get(name)
    if not definition:
        raise IntegrationProviderError("Unsupported integration operation.")
    if operation == "describe_operation":
        return {"operation": name, **definition}
    if operation not in ("read_api", "write_api") or definition["write"] != (
        operation == "write_api"
    ):
        raise IntegrationProviderError(
            "Integration operation requires the matching read or write tool."
        )
    params, body = arguments.get("params", {}), arguments.get("body", {})
    _validate(params, definition["params_schema"])
    _validate(body, definition["body_schema"])
    if len(json.dumps([params, body], ensure_ascii=False).encode()) > 128 * 1024:
        raise IntegrationProviderError("Integration request exceeds its limit.")
    path = definition["path"]
    for key in definition["path_params"]:
        path = path.replace("{" + key + "}", _path_value(params[key]))
    query = {
        key: str(value).lower()
        if type(value) is bool
        else json.dumps(value, ensure_ascii=False)
        if isinstance(value, dict)
        else value
        for key, value in params.items()
        if key not in definition["path_params"]
    }
    if name in ("im.messages.create", "im.messages.reply"):
        body = {**body, "uuid": hashlib.sha256(request_id.encode()).hexdigest()[:32]}
    url = _ENDPOINTS[_brand(credentials.get("brand"))][1] + path
    if query:
        url += "?" + urlencode(query, doseq=True)
    result = await request(
        definition["method"],
        url,
        headers={"Authorization": "Bearer " + credentials["access_token"]},
        body=body or None,
        provider="feishu",
        side_effecting=definition["write"],
    )
    if (
        not isinstance(result, dict)
        or result.get("code", 0) != 0
        or result.get("error")
    ):
        raise IntegrationProviderError(
            "Integration request failed. Check the account authorization and application permissions."
        )
    return result
