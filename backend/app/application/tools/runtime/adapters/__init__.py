"""Provider adapters behind the unified Tool runtime contract."""

import ast
import json
import re
from typing import Any

from app.application.artifacts.service import create_generated_artifact
from app.entities.tools import McpServer, ToolSnapshot
from app.infra.sandbox.client import (
    WorkflowSandboxBusyError,
    WorkflowSandboxError,
    execute_artifact_code,
    execute_skill_artifact,
    execute_workflow_code,
)
from app.infra.config.settings import Settings
from app.entities.defaults import APP_TIMEZONE, utc_now
from app.infra.db.session import get_session_factory
from app.ports.mcp import McpClientError, call_mcp_tool
from app.application.tools.runtime.contracts import (
    ToolAdapter,
    ToolAdapterBusy,
    ToolInvocationContext,
    ToolRuntimeResult,
)
from app.domain.artifacts.services import artifact_format_from_filename
from app.domain.tools.mcp.service import mcp_server_connection

from app.application.tools.runtime.adapters.builtin import BuiltinToolAdapter
from app.application.tools.runtime.adapters.mcp import McpToolAdapter
from app.application.tools.runtime.adapters.python_tool import PythonToolAdapter

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
