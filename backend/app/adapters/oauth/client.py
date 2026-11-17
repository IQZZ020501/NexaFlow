import ipaddress
import json
from urllib.parse import quote, urlparse

import httpx2

from app.adapters.mcp.client import (
    _hardened_http_client_factory,
    validate_mcp_destination,
)
from app.ports.mcp import McpClientError
from app.ports.oauth import OAuthExchangeError


async def validate_endpoint(url, *, allow_private=False):
    if (
        not isinstance(url, str)
        or len(url) > 2048
        or any(ord(c) < 33 or c == "\\" for c in url)
    ):
        raise OAuthExchangeError("Invalid OAuth endpoint.")
    parsed = urlparse(url)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise OAuthExchangeError("Invalid OAuth endpoint port.") from exc
    try:
        loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        loopback = parsed.hostname == "localhost"
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not (
            parsed.scheme == "https"
            or parsed.scheme == "http"
            and loopback
            and allow_private
        )
    ):
        raise OAuthExchangeError(
            "OAuth endpoints require HTTPS; local HTTP testing requires the private-network override."
        )
    try:
        return await validate_mcp_destination(url, allow_private)
    except (McpClientError, ValueError) as exc:
        raise OAuthExchangeError(
            "OAuth endpoint is unavailable or disallowed."
        ) from exc


async def post(
    url,
    data,
    *,
    client_auth="none",
    client_id="",
    client_secret="",
    allow_private=False,
):
    destination = await validate_endpoint(url, allow_private=allow_private)
    values = dict(data)
    auth = None
    if client_auth == "client_secret_basic":
        auth = httpx2.BasicAuth(
            quote(client_id, safe=""), quote(client_secret, safe="")
        )
    else:
        values["client_id"] = client_id
        if client_auth == "client_secret_post":
            values["client_secret"] = client_secret
    try:
        async with _hardened_http_client_factory(
            destination=destination, timeout=httpx2.Timeout(15), auth=auth
        ) as client:
            async with client.stream(
                "POST", url, data=values, headers={"Accept": "application/json"}
            ) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 64 * 1024:
                        raise OAuthExchangeError("OAuth response exceeds its limit.")
                if not 200 <= response.status_code < 300:
                    raise OAuthExchangeError(
                        "OAuth request failed; reconnect the source or check its client configuration."
                    )
                if not raw:
                    return {}
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError()
                return result
    except OAuthExchangeError:
        raise
    except (httpx2.HTTPError, ValueError) as exc:
        raise OAuthExchangeError(
            "OAuth response was unavailable; reconnect before retrying authorization."
        ) from exc
