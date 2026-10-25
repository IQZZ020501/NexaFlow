import asyncio
import hashlib
import ipaddress
import json
import logging
import socket
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import Any
from urllib.parse import urlparse

import httpcore2
import httpx2
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, ListToolsResult

from app.adapters.mcp.sessions import SessionKey, session_pool
from app.infra.config.settings import Settings
from app.infra.observability.errors import log_error
from app.infra.observability.logger import get_logger, log_event
from app.infra.tools.mcp_stdio import (
    McpStdioConfigError,
    serialize_mcp_stdio_config,
    validate_mcp_stdio_config_runtime,
)
from app.ports.execution import (
    ExecutionBusy,
    ExecutionNotStarted,
    ExecutionScope,
    build_execution_platform,
    execution_scope,
)
from app.ports.mcp import (
    MAX_MCP_RESULT_BYTES,
    MAX_MCP_STORED_RESULT_BYTES,
    MAX_MCP_TOOL_PAGES,
    McpCallResult,
    McpClientError,
    McpConnection,
    McpDiscovery,
    McpServerBusy,
    normalize_mcp_url,
)

logger = get_logger(__name__)

MAX_MCP_TOOLS = 64
MAX_MCP_TOOL_DESCRIPTION_CHARS = 1_000
MAX_MCP_TOOL_SCHEMA_CHARS = 20_000


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
async def _open_remote_client(
    connection: McpConnection,
    settings: Settings,
    timeout_seconds: float,
    *,
    bridge=None,
) -> AsyncIterator[Client]:
    """Connect and initialize within ``timeout_seconds``; no tool call is sent."""
    async with AsyncExitStack() as stack:
        try:
            async with asyncio.timeout(timeout_seconds):
                if connection.url is None and bridge is None:
                    raise McpClientError("MCP server URL is required.")
                normalized_url = normalize_mcp_url(
                    bridge.url if bridge else connection.url,
                    preserve_trailing_slash=connection.transport == "sse",
                )
                destination = await validate_mcp_destination(
                    normalized_url,
                    bridge is not None or settings.mcp_allow_private_networks
                    and connection.network_policy == "deployment",
                )
                headers = (
                    {"Authorization": f"Bearer {connection.bearer_token}"}
                    if connection.bearer_token
                    else {}
                )
                if bridge is not None:
                    if not normalized_url.startswith(f"{settings.opensandbox_url.rstrip('/')}/v1/sandboxes/"):
                        raise McpClientError("Invalid control-plane proxy endpoint.", request_sent=False)
                    headers = bridge.headers
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
                client = await stack.enter_async_context(
                    Client(
                        transport,
                        read_timeout_seconds=timeout_seconds,
                        cache=None,
                    )
                )
        except McpClientError as exc:
            exc.request_sent = False
            raise
        except Exception as exc:
            log_error(
                logger,
                "MCP server connection failed.",
                exc,
                transport=connection.transport,
                target=connection.url or "",
            )
            raise McpClientError(
                "MCP server request failed.", request_sent=False
            ) from exc
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
    entered = False
    try:
        async with asyncio.timeout(timeout_seconds):
            if connection.transport in {"streamable_http", "sse"}:
                async with _open_remote_client(
                    connection, settings, timeout_seconds
                ) as client:
                    entered = True
                    yield client
            elif connection.transport == "stdio":
                config = connection.stdio_config
                if config is None:
                    raise McpClientError("MCP stdio configuration is required.")
                try:
                    validate_mcp_stdio_config_runtime(config)
                except McpStdioConfigError as exc:
                    raise McpClientError(str(exc)) from exc
                # Only the image-local runner starts processes. API/Worker
                # never execute registrations or inherit their environment.
                entered = True
                yield _SandboxMcpClient(connection, settings, timeout_seconds)
            else:
                raise McpClientError("Unsupported MCP transport.")
    except McpClientError as exc:
        if not entered:
            exc.request_sent = False
        raise
    except Exception as exc:
        log_error(
            logger,
            "MCP server request failed.",
            exc,
            transport=connection.transport,
            target=target,
        )
        raise McpClientError(
            "MCP server request failed.", request_sent=entered
        ) from exc


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
                            tool.annotations.model_dump(
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
) -> McpCallResult:
    started_at = time.perf_counter()
    timeout_seconds = settings.mcp_request_timeout_seconds
    meta = {"nexaflow/idempotencyKey": idempotency_key} if idempotency_key else None

    async def invoke(client) -> Any:
        return await client.call_tool(
            tool_name,
            arguments,
            read_timeout_seconds=timeout_seconds,
            meta=meta,
        )

    scope = execution_scope.get()
    if (
        connection.transport in {"streamable_http", "stdio"}
        and scope is not None
        and scope.run_id
    ):
        result = await _call_in_run_session(
            connection, settings, scope.run_id, invoke
        )
    else:
        async with mcp_client(connection, settings, timeout_seconds) as client:
            result = await invoke(client)

    call_result = _bounded_call_result(
        McpCallResult(
            structured_content=result.structured_content,
            content=[
                item.model_dump(mode="json", by_alias=True, exclude_none=True)
                for item in result.content
            ],
            is_error=bool(result.is_error),
            meta=getattr(result, "meta", None),
        )
    )
    log_event(
        logger,
        logging.INFO,
        "MCP tool call completed.",
        tool_name=tool_name,
        is_error=bool(result.is_error),
        duration_ms=round((time.perf_counter() - started_at) * 1000),
    )
    return call_result


async def _call_in_run_session(connection, settings, run_id, invoke) -> Any:
    """Reuse one initialized session for every call of the same Run."""
    timeout_seconds = settings.mcp_request_timeout_seconds
    stdio_config = serialize_mcp_stdio_config(connection.stdio_config) if connection.transport == "stdio" else None
    key = SessionKey(
        run_id=run_id,
        url=connection.url or f"stdio:{hashlib.sha256(stdio_config.encode()).hexdigest()}",
        credential=hashlib.sha256(
            (connection.bearer_token or "").encode()
        ).hexdigest(),
        network_policy=connection.network_policy,
        workspace_id=connection.workspace_id,
    )

    async def bounded(client) -> Any:
        async with asyncio.timeout(timeout_seconds):
            return await invoke(client)

    @asynccontextmanager
    async def open_stdio():
        validate_mcp_stdio_config_runtime(connection.stdio_config)
        config = json.loads(stdio_config)
        domains = config.pop("egress_domains", [])
        opened = False
        try:
            async with build_execution_platform(settings).mcp_host(config, domains, hashlib.sha256(stdio_config.encode()).hexdigest()) as bridge:
                async with _open_remote_client(McpConnection(transport="streamable_http"), settings, timeout_seconds, bridge=bridge) as client:
                    opened = True
                    yield client
        except ExecutionBusy as exc:
            raise McpServerBusy("MCP server host is busy.") from exc
        except (ExecutionNotStarted, ValueError) as exc:
            raise McpClientError("MCP server host could not start.", request_sent=False) from exc
        except McpClientError:
            raise
        except Exception as exc:
            raise McpClientError("MCP bridge request failed.", request_sent=opened) from exc

    try:
        return await session_pool().call(
            key,
            open_stdio if stdio_config is not None else partial(_open_remote_client, connection, settings, timeout_seconds),
            bounded,
        )
    except McpClientError:
        raise
    except Exception as exc:
        log_error(
            logger,
            "MCP server request failed.",
            exc,
            transport=connection.transport,
            target=connection.url or "",
        )
        raise McpClientError("MCP server request failed.") from exc


def _bounded_call_result(result: McpCallResult) -> McpCallResult:
    """Preserve results for durable storage, with a hard transport safety cap."""
    try:
        encoded = json.dumps(result.payload(), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise McpClientError("MCP tool returned an invalid result.") from exc
    size = len(encoded.encode())
    if size <= MAX_MCP_STORED_RESULT_BYTES:
        return result
    raw = encoded.encode()
    notice = (
        f"\n[Result exceeds the {MAX_MCP_STORED_RESULT_BYTES}-byte storage limit "
        f"({size} bytes). Only this prefix is available; the full result was not "
        "saved. Request a narrower result if the server supports it.]"
    )
    budget = MAX_MCP_RESULT_BYTES
    while True:
        prefix = raw[:budget].decode("utf-8", errors="ignore")
        truncated = McpCallResult(
            content=[{"type": "text", "text": prefix + notice}],
            is_error=result.is_error,
            meta={
                "nexaflow/truncated": True,
                "nexaflow/full_result_available": False,
                "nexaflow/result_bytes": size,
            },
        )
        bounded = json.dumps(truncated.payload(), ensure_ascii=False)
        if len(bounded.encode()) <= MAX_MCP_RESULT_BYTES:
            return truncated
        budget = budget * 3 // 4


class _SandboxMcpClient:
    def __init__(self, connection, settings, timeout_seconds):
        self.connection = connection
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    async def _request(self, operation, **arguments):
        config = json.loads(serialize_mcp_stdio_config(self.connection.stdio_config))
        domains = config.pop("egress_domains", [])
        scope = None
        if execution_scope.get() is None and self.connection.workspace_id:
            from uuid import uuid4

            scope = execution_scope.set(
                ExecutionScope(
                    self.connection.workspace_id, f"mcp-{operation}-{uuid4()}"
                )
            )
        try:
            response = await self._execute(operation, config, domains, arguments)
        except ExecutionBusy as exc:
            raise McpServerBusy("MCP server host is busy.") from exc
        except ExecutionNotStarted as exc:
            raise McpClientError(
                "Sandboxed MCP server could not start.", request_sent=False
            ) from exc
        finally:
            if scope is not None:
                execution_scope.reset(scope)
        if not response.get("ok") or not isinstance(response.get("mcp"), dict):
            raise McpClientError("Sandboxed MCP server request failed.")
        return response["mcp"]

    async def _execute(self, operation, config, domains, arguments):
        return await build_execution_platform(self.settings).execute(
            {
                "mcp": {
                    "operation": operation,
                    "config": config,
                    "timeout": self.timeout_seconds,
                    **arguments,
                },
                "network_domains": domains,
                "limits": {"timeout_ms": round(self.timeout_seconds * 1000)},
            },
            timeout_seconds=self.timeout_seconds,
            max_output_bytes=2 * 1024 * 1024,
        )

    async def list_tools(self, cursor=None, cache_mode=None):
        return ListToolsResult.model_validate(await self._request("discover"))

    async def call_tool(self, name, arguments, read_timeout_seconds=None, meta=None):
        return CallToolResult.model_validate(
            await self._request("call", name=name, arguments=arguments, meta=meta)
        )


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
    ) -> McpCallResult:
        return await call_mcp_tool(
            connection,
            self.settings,
            tool_name,
            arguments,
            idempotency_key,
        )
