import asyncio
import ipaddress
import json
import logging
import os
import socket
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal
from urllib.parse import urlparse

import httpcore2
import httpx2
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from app.infrastructure.config import Settings
from app.infrastructure.errors import ExternalServiceError, log_error
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.mcp_stdio import (
    McpStdioConfig,
    McpStdioConfigError,
    validate_mcp_stdio_config_runtime,
)

logger = get_logger(__name__)

MAX_MCP_TOOLS = 64
MAX_MCP_TOOL_PAGES = 32
MAX_MCP_RESULT_CHARS = 20_000
MAX_MCP_TOOL_DESCRIPTION_CHARS = 1_000
MAX_MCP_TOOL_SCHEMA_CHARS = 20_000


class McpClientError(ExternalServiceError):
    pass


McpTransport = Literal["streamable_http", "sse", "stdio"]


@dataclass(frozen=True)
class McpConnection:
    transport: McpTransport
    url: str | None = None
    bearer_token: str | None = None
    stdio_config: McpStdioConfig | None = None
    network_policy: Literal["public_only", "deployment"] = "public_only"


@dataclass(frozen=True)
class McpDiscovery:
    tools: list[dict[str, Any]]


@dataclass(frozen=True)
class McpResolvedDestination:
    hostname: str
    port: int
    addresses: tuple[str, ...]


class _PinnedNetworkBackend(httpcore2.AsyncNetworkBackend):
    def __init__(self, destination: McpResolvedDestination) -> None:
        self.destination = destination
        self._backend = httpcore2.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        if host.lower() != self.destination.hostname or port != self.destination.port:
            raise httpcore2.ConnectError("MCP request destination changed.")

        last_error: Exception | None = None
        for address in self.destination.addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options=None,
    ):
        raise httpcore2.ConnectError("MCP Unix sockets are not allowed.")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def _pinned_http_transport(
    destination: McpResolvedDestination,
) -> httpx2.AsyncHTTPTransport:
    transport = httpx2.AsyncHTTPTransport(trust_env=False)
    # httpx2 2.5 has no public resolver hook; its pool accepts the backend
    # internally and is covered by the pinned-connection regression test.
    transport._pool._network_backend = _PinnedNetworkBackend(destination)
    return transport


def normalize_mcp_url(value: str, *, preserve_trailing_slash: bool = False) -> str:
    stripped = value.strip()
    url = stripped if preserve_trailing_slash else stripped.rstrip("/")
    parsed = urlparse(url)
    try:
        parsed.port
    except ValueError as exc:
        raise McpClientError("Invalid MCP server URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise McpClientError("Invalid MCP server URL.")
    return url


def is_private_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


async def validate_mcp_destination(
    url: str,
    allow_private_networks: bool,
) -> McpResolvedDestination | None:
    if allow_private_networks:
        return None
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        raise McpClientError("Invalid MCP server URL.")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            parsed.port or (80 if parsed.scheme == "http" else 443),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise McpClientError("MCP server hostname could not be resolved.") from exc
    resolved = tuple(dict.fromkeys(item[4][0] for item in addresses))
    if not resolved or any(is_private_address(address) for address in resolved):
        raise McpClientError("Private MCP server addresses are not allowed.")
    return McpResolvedDestination(
        hostname=hostname.encode("idna").decode("ascii").lower(),
        port=parsed.port or (80 if parsed.scheme == "http" else 443),
        addresses=resolved,
    )


@asynccontextmanager
async def _hardened_http_client_factory(
    *,
    headers: dict[str, Any] | None = None,
    auth: httpx2.Auth | None = None,
    timeout: httpx2.Timeout | None = None,
    destination: McpResolvedDestination | None = None,
) -> AsyncIterator[httpx2.AsyncClient]:
    async with httpx2.AsyncClient(
        headers=headers,
        auth=auth,
        timeout=timeout,
        transport=(
            _pinned_http_transport(destination)
            if destination is not None
            else None
        ),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        yield client


@asynccontextmanager
async def mcp_client(
    connection: McpConnection,
    settings: Settings,
    timeout_seconds: float,
) -> AsyncIterator[Client]:
    target = connection.url or (
        connection.stdio_config.command if connection.stdio_config else ""
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            async with AsyncExitStack() as stack:
                if connection.transport in {"streamable_http", "sse"}:
                    if connection.url is None:
                        raise McpClientError("MCP server URL is required.")
                    normalized_url = normalize_mcp_url(
                        connection.url,
                        preserve_trailing_slash=connection.transport == "sse",
                    )
                    destination = await validate_mcp_destination(
                        normalized_url,
                        settings.mcp_allow_private_networks
                        and connection.network_policy == "deployment",
                    )
                    headers = (
                        {"Authorization": f"Bearer {connection.bearer_token}"}
                        if connection.bearer_token
                        else {}
                    )
                    if connection.transport == "streamable_http":
                        http_client = await stack.enter_async_context(
                            _hardened_http_client_factory(
                                headers=headers,
                                timeout=timeout_seconds,
                                destination=destination,
                            )
                        )
                        transport = streamable_http_client(
                            normalized_url,
                            http_client=http_client,
                        )
                    else:
                        transport = sse_client(
                            normalized_url,
                            headers=headers,
                            timeout=timeout_seconds,
                            sse_read_timeout=timeout_seconds,
                            httpx_client_factory=partial(
                                _hardened_http_client_factory,
                                destination=destination,
                            ),
                        )
                elif connection.transport == "stdio":
                    config = connection.stdio_config
                    if config is None:
                        raise McpClientError("MCP stdio configuration is required.")
                    try:
                        validate_mcp_stdio_config_runtime(config)
                    except McpStdioConfigError as exc:
                        raise McpClientError(str(exc)) from exc
                    errlog = stack.enter_context(
                        open(os.devnull, "w", encoding="utf-8")
                    )
                    transport = stdio_client(
                        StdioServerParameters(
                            command=config.command,
                            args=list(config.args),
                            env=dict(config.env),
                            cwd=config.cwd,
                        ),
                        errlog=errlog,
                    )
                else:
                    raise McpClientError("Unsupported MCP transport.")

                client = await stack.enter_async_context(
                    Client(
                        transport,
                        read_timeout_seconds=timeout_seconds,
                        cache=None,
                    )
                )
                yield client
    except McpClientError:
        raise
    except Exception as exc:
        log_error(
            logger,
            "MCP server request failed.",
            exc,
            transport=connection.transport,
            target=target,
        )
        raise McpClientError("MCP server request failed.") from exc


async def discover_mcp_tools(
    connection: McpConnection,
    settings: Settings,
) -> McpDiscovery:
    discovered: list[dict[str, Any]] = []
    names: set[str] = set()
    async with mcp_client(
        connection,
        settings,
        settings.mcp_request_timeout_seconds,
    ) as client:
        cursor: str | None = None
        for _ in range(MAX_MCP_TOOL_PAGES):
            result = await client.list_tools(cursor=cursor, cache_mode="reload")
            for tool in result.tools:
                if tool.name in names:
                    continue
                if not tool.name or len(tool.name) > 255:
                    raise McpClientError("MCP server returned an invalid tool name.")
                if len(discovered) >= MAX_MCP_TOOLS:
                    raise McpClientError("MCP server exposes too many tools.")
                input_schema = tool.input_schema
                if (
                    not isinstance(input_schema, dict)
                    or input_schema.get("type") != "object"
                ):
                    raise McpClientError("MCP server returned an invalid tool schema.")
                try:
                    schema_size = len(json.dumps(input_schema, ensure_ascii=False))
                except (TypeError, ValueError) as exc:
                    raise McpClientError(
                        "MCP server returned an invalid tool schema."
                    ) from exc
                if schema_size > MAX_MCP_TOOL_SCHEMA_CHARS:
                    raise McpClientError("MCP tool schema is too large.")
                names.add(tool.name)
                discovered.append(
                    {
                        "name": tool.name,
                        "description": (tool.description or "")[
                            :MAX_MCP_TOOL_DESCRIPTION_CHARS
                        ],
                        "input_schema": input_schema,
                        "annotations": (
                            getattr(tool, "annotations").model_dump(
                                mode="json",
                                by_alias=True,
                                exclude_none=True,
                            )
                            if getattr(tool, "annotations", None) is not None
                            else None
                        ),
                    }
                )
            cursor = result.next_cursor
            if cursor is None:
                break
        else:
            raise McpClientError("MCP server returned too many tool pages.")
    log_event(
        logger,
        logging.INFO,
        "MCP tool discovery completed.",
        tool_count=len(discovered),
        transport=connection.transport,
    )
    return McpDiscovery(tools=discovered)


async def call_mcp_tool(
    connection: McpConnection,
    settings: Settings,
    tool_name: str,
    arguments: dict[str, Any],
    idempotency_key: str | None = None,
) -> tuple[str, bool]:
    started_at = time.perf_counter()
    async with mcp_client(
        connection,
        settings,
        settings.mcp_request_timeout_seconds,
    ) as client:
        result = await client.call_tool(
            tool_name,
            arguments,
            read_timeout_seconds=settings.mcp_request_timeout_seconds,
            meta=(
                {"nexaflow/idempotencyKey": idempotency_key}
                if idempotency_key
                else None
            ),
        )

    payload: Any = result.structured_content
    if payload is None:
        payload = [
            item.model_dump(mode="json", by_alias=True, exclude_none=True)
            for item in result.content
        ]
    content = json.dumps(payload, ensure_ascii=False)
    if len(content) > MAX_MCP_RESULT_CHARS:
        content = content[:MAX_MCP_RESULT_CHARS] + "\n[truncated]"
    log_event(
        logger,
        logging.INFO,
        "MCP tool call completed.",
        tool_name=tool_name,
        is_error=bool(result.is_error),
        duration_ms=round((time.perf_counter() - started_at) * 1000),
    )
    return content, bool(result.is_error)


class MultiTransportMcpClient:
    """Adapter implementing the ``app.ports.mcp.McpClient`` contract."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def discover_mcp_tools(
        self,
        connection: McpConnection,
    ) -> McpDiscovery:
        return await discover_mcp_tools(connection, self.settings)

    async def call_mcp_tool(
        self,
        connection: McpConnection,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> tuple[str, bool]:
        return await call_mcp_tool(
            connection,
            self.settings,
            tool_name,
            arguments,
            idempotency_key,
        )
