"""MCP client port.

Business code discovers and invokes MCP tools through this contract instead
of importing ``app.capabilities.mcp.client`` directly.
"""

from typing import Any, Protocol

from app.capabilities.mcp.client import (
    MAX_MCP_TOOL_PAGES,
    McpConnection,
    McpClientError,
    McpDiscovery,
    McpTransport,
    MultiTransportMcpClient,
    normalize_mcp_url as _normalize_mcp_url,
)
from app.infrastructure.config import Settings


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


def build_mcp_client(settings: Settings) -> McpClient:
    return MultiTransportMcpClient(settings)


async def discover_mcp_tools(
    connection: McpConnection,
    settings: Settings,
) -> McpDiscovery:
    return await build_mcp_client(settings).discover_mcp_tools(connection)


async def call_mcp_tool(
    connection: McpConnection,
    settings: Settings,
    tool_name: str,
    arguments: dict[str, Any],
    idempotency_key: str | None = None,
) -> tuple[str, bool]:
    return await build_mcp_client(settings).call_mcp_tool(
        connection,
        tool_name,
        arguments,
        idempotency_key,
    )


def normalize_mcp_url(value: str, *, preserve_trailing_slash: bool = False) -> str:
    return _normalize_mcp_url(
        value,
        preserve_trailing_slash=preserve_trailing_slash,
    )


__all__ = [
    "MAX_MCP_TOOL_PAGES",
    "McpConnection",
    "McpClient",
    "McpClientError",
    "McpDiscovery",
    "McpTransport",
    "build_mcp_client",
    "call_mcp_tool",
    "discover_mcp_tools",
    "normalize_mcp_url",
]
