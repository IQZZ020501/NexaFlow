"""Provider adapters behind the unified Tool runtime contract."""

from app.application.tools.runtime.adapters.builtin import BuiltinToolAdapter
from app.application.tools.runtime.adapters.mcp import McpToolAdapter
from app.application.tools.runtime.adapters.python_tool import PythonToolAdapter
from app.application.tools.runtime.contracts import ToolAdapter
from app.entities.tools import McpServer, ToolSnapshot
from app.infra.config.settings import Settings


def build_tool_adapter(
    snapshot: ToolSnapshot,
    settings: Settings,
    server: McpServer | None = None,
) -> ToolAdapter:
    if snapshot.kind == "builtin":
        return BuiltinToolAdapter(settings)
    if snapshot.kind == "python":
        return PythonToolAdapter(settings)
    if snapshot.kind == "mcp" and server is not None:
        return McpToolAdapter(settings, server)
    raise ValueError("Tool provider is unavailable.")


__all__ = [
    "BuiltinToolAdapter",
    "McpToolAdapter",
    "PythonToolAdapter",
    "build_tool_adapter",
]
