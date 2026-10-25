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
MAX_MCP_RESULT_BYTES = 24 * 1024
MAX_MCP_STORED_RESULT_BYTES = 2 * 1024 * 1024


class McpClientError(ExternalServiceError):
    """An MCP request failed.

    ``request_sent`` is False only when the server cannot have received the
    tool call, so a side-effecting call is known not to have run.
    """

    def __init__(self, message: str = "", *, request_sent: bool = True) -> None:
        super().__init__(message)
        self.request_sent = request_sent


class McpServerBusy(McpClientError):
    """The MCP server host has no capacity; nothing was sent."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message, request_sent=False)


McpTransport = Literal["streamable_http", "sse", "stdio"]


@dataclass(frozen=True)
class McpConnection:
    transport: McpTransport
    url: str | None = None
    bearer_token: str | None = None
    stdio_config: McpStdioConfig | None = None
    network_policy: Literal["public_only", "deployment"] = "public_only"
    workspace_id: str | None = None


@dataclass(frozen=True)
class McpDiscovery:
    tools: list[dict[str, Any]]


@dataclass(frozen=True)
class McpCallResult:
    content: list[dict[str, Any]]
    structured_content: Any | None = None
    is_error: bool = False
    meta: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        """Keep MCP content blocks even when structuredContent is also present."""
        value = {"content": self.content, "isError": self.is_error}
        if self.structured_content is not None:
            value["structuredContent"] = self.structured_content
        if self.meta is not None:
            value["_meta"] = self.meta
        return value


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
    ) -> McpCallResult: ...


def normalize_mcp_url(value: str, *, preserve_trailing_slash: bool = False) -> str:
    from urllib.parse import urlparse

    stripped = value.strip()
    url = stripped if preserve_trailing_slash else stripped.rstrip("/")
    parsed = urlparse(url)
    try:
        _ = parsed.port
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
) -> McpDiscovery:
    return await build_mcp_client(settings).discover_mcp_tools(connection)


async def call_mcp_tool(
    connection: McpConnection,
    settings: Settings,
    tool_name: str,
    arguments: dict[str, Any],
    idempotency_key: str | None = None,
) -> McpCallResult:
    return await build_mcp_client(settings).call_mcp_tool(
        connection,
        tool_name,
        arguments,
        idempotency_key,
    )


async def close_mcp_run_sessions(run_id: str) -> None:
    """Close the MCP connections a Run kept open in this process."""
    from app.adapters.mcp.sessions import close_run_sessions

    await close_run_sessions(run_id)


__all__ = [
    "MAX_MCP_TOOL_PAGES",
    "MAX_MCP_RESULT_BYTES",
    "MAX_MCP_STORED_RESULT_BYTES",
    "McpClient",
    "McpClientError",
    "McpCallResult",
    "McpConnection",
    "McpDiscovery",
    "McpServerBusy",
    "McpTransport",
    "build_mcp_client",
    "call_mcp_tool",
    "close_mcp_run_sessions",
    "discover_mcp_tools",
    "normalize_mcp_url",
]
