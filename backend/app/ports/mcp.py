"""MCP client port.

Business code discovers and invokes MCP tools through this contract and
the value/error types below; concrete transport implementations live in
``app.adapters.mcp``. This module never imports adapters or infra at
import time - delegates resolve the current adapter lazily.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from app.ports.errors import ExternalServiceError

if TYPE_CHECKING:
    from app.infra.config.settings import Settings
    from app.infra.tools.mcp_stdio import McpStdioConfig

MAX_MCP_TOOL_PAGES = 32


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


class McpClient(Protocol):
    async def discover_mcp_tools(
        self,
        connection: McpConnection,
    ) -> McpDiscovery: ...

    async def call_mcp_tool(
        self,
        connection: McpConnection,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> tuple[str, bool]: ...


def normalize_mcp_url(value: str, *, preserve_trailing_slash: bool = False) -> str:
    from urllib.parse import urlparse

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


def build_mcp_client(settings: Settings) -> McpClient:
    from app.adapters.mcp.client import MultiTransportMcpClient

    return MultiTransportMcpClient(settings)


async def discover_mcp_tools(
    connection: McpConnection,
    settings: Settings,
    *,
    mcp_allowed_private_networks: bool = False,
) -> McpDiscovery:
    from app.adapters.mcp.client import discover_mcp_tools as _discover

    return await _discover(
        connection,
        settings,
        mcp_allowed_private_networks=mcp_allowed_private_networks,
    )


async def call_mcp_tool(
    connection: McpConnection,
    settings: Settings,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    idempotency_key: str | None = None,
) -> tuple[str, bool]:
    from app.adapters.mcp.client import call_mcp_tool as _call

    return await _call(
        connection,
        settings,
        tool_name,
        arguments,
        idempotency_key=idempotency_key,
    )


__all__ = [
    "MAX_MCP_TOOL_PAGES",
    "McpClient",
    "McpClientError",
    "McpConnection",
    "McpDiscovery",
    "McpTransport",
    "build_mcp_client",
    "call_mcp_tool",
    "discover_mcp_tools",
    "normalize_mcp_url",
]
