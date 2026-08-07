"""MCP client port.

Business code discovers and invokes MCP tools through this contract instead
of importing ``app.capabilities.mcp.client`` directly.
"""

from typing import Any, Protocol

from app.capabilities.mcp.client import (
    MAX_MCP_TOOL_PAGES,
    McpClientError,
    StreamableHttpMcpClient,
)
from app.infrastructure.config import Settings


class McpClient(Protocol):
    def normalize_mcp_url(self, value: str) -> str: ...

    async def discover_mcp_tools(
        self,
        url: str,
        bearer_token: str | None,
        allow_private_networks: bool,
        timeout_seconds: float,
    ) -> list[dict[str, Any]]: ...

    async def call_mcp_tool(
        self,
        url: str,
        bearer_token: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        allow_private_networks: bool,
        timeout_seconds: float,
        idempotency_key: str | None = None,
    ) -> tuple[str, bool]: ...


def build_mcp_client(settings: Settings | None = None) -> McpClient:
    return StreamableHttpMcpClient()


async def discover_mcp_tools(
    url: str,
    bearer_token: str | None,
    allow_private_networks: bool,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    return await build_mcp_client().discover_mcp_tools(
        url,
        bearer_token,
        allow_private_networks,
        timeout_seconds,
    )


async def call_mcp_tool(
    url: str,
    bearer_token: str | None,
    tool_name: str,
    arguments: dict[str, Any],
    allow_private_networks: bool,
    timeout_seconds: float,
    idempotency_key: str | None = None,
) -> tuple[str, bool]:
    return await build_mcp_client().call_mcp_tool(
        url,
        bearer_token,
        tool_name,
        arguments,
        allow_private_networks,
        timeout_seconds,
        idempotency_key,
    )


def normalize_mcp_url(value: str) -> str:
    return build_mcp_client().normalize_mcp_url(value)


__all__ = [
    "MAX_MCP_TOOL_PAGES",
    "McpClient",
    "McpClientError",
    "build_mcp_client",
    "call_mcp_tool",
    "discover_mcp_tools",
    "normalize_mcp_url",
]
