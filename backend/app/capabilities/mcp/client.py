import asyncio
import ipaddress
import json
import logging
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.infrastructure.errors import ExternalServiceError, log_error
from app.infrastructure.logger import get_logger, log_event

logger = get_logger(__name__)

MAX_MCP_TOOLS = 64
MAX_MCP_TOOL_PAGES = 32
MAX_MCP_RESULT_CHARS = 20_000
MAX_MCP_TOOL_DESCRIPTION_CHARS = 1_000
MAX_MCP_TOOL_SCHEMA_CHARS = 20_000


class McpClientError(ExternalServiceError):
    pass


def normalize_mcp_url(value: str) -> str:
    url = value.strip().rstrip("/")
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


async def validate_mcp_destination(url: str, allow_private_networks: bool) -> None:
    parsed = urlparse(url)
    if allow_private_networks:
        return
    if parsed.scheme != "https":
        raise McpClientError("Public MCP servers must use HTTPS.")

    hostname = parsed.hostname
    if hostname is None:
        raise McpClientError("Invalid MCP server URL.")
    port = parsed.port or 443
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise McpClientError("MCP server hostname could not be resolved.") from exc
    if not addresses or any(is_private_address(item[4][0]) for item in addresses):
        raise McpClientError("Private MCP server addresses are not allowed.")


@asynccontextmanager
async def mcp_client(
    url: str,
    bearer_token: str | None,
    allow_private_networks: bool,
    timeout_seconds: float,
) -> AsyncIterator[Client]:
    normalized_url = normalize_mcp_url(url)
    await validate_mcp_destination(normalized_url, allow_private_networks)
    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
    try:
        async with httpx2.AsyncClient(
            headers=headers,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as http_client:
            transport = streamable_http_client(
                normalized_url,
                http_client=http_client,
            )
            async with Client(
                transport,
                read_timeout_seconds=timeout_seconds,
                cache=None,
            ) as client:
                yield client
    except McpClientError:
        raise
    except Exception as exc:
        log_error(logger, "MCP server request failed.", exc, url=url)
        raise McpClientError("MCP server request failed.") from exc


async def discover_mcp_tools(
    url: str,
    bearer_token: str | None,
    allow_private_networks: bool,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    names: set[str] = set()
    async with mcp_client(
        url,
        bearer_token,
        allow_private_networks,
        timeout_seconds,
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
        url=url,
    )
    return discovered


async def call_mcp_tool(
    url: str,
    bearer_token: str | None,
    tool_name: str,
    arguments: dict[str, Any],
    allow_private_networks: bool,
    timeout_seconds: float,
) -> tuple[str, bool]:
    started_at = time.perf_counter()
    async with mcp_client(
        url,
        bearer_token,
        allow_private_networks,
        timeout_seconds,
    ) as client:
        result = await client.call_tool(
            tool_name,
            arguments,
            read_timeout_seconds=timeout_seconds,
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


class StreamableHttpMcpClient:
    """Adapter implementing the ``app.ports.mcp.McpClient`` contract."""

    def normalize_mcp_url(self, value: str) -> str:
        return normalize_mcp_url(value)

    async def discover_mcp_tools(
        self,
        url: str,
        bearer_token: str | None,
        allow_private_networks: bool,
        timeout_seconds: float,
    ) -> list[dict[str, Any]]:
        return await discover_mcp_tools(
            url,
            bearer_token,
            allow_private_networks,
            timeout_seconds,
        )

    async def call_mcp_tool(
        self,
        url: str,
        bearer_token: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        allow_private_networks: bool,
        timeout_seconds: float,
    ) -> tuple[str, bool]:
        return await call_mcp_tool(
            url,
            bearer_token,
            tool_name,
            arguments,
            allow_private_networks,
            timeout_seconds,
        )
