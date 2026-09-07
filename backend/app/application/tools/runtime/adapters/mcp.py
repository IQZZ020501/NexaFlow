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
from app.application.tools.runtime.adapters._common import (  # noqa: F401
    DIRECT_ARTIFACT_CONTENT_FORMATS,
    _UNAVAILABLE_ARTIFACT_IMPORTS,
    _artifact_code_preflight,
    _artifact_error_message,
    _failure,
    _is_direct_artifact_content,
    _redirect_legacy_artifact_path,
)

class McpToolAdapter:
    kind = "mcp"

    def __init__(self, settings: Settings, server: McpServer) -> None:
        self.settings = settings
        self.server = server

    async def invoke(
        self,
        snapshot: ToolSnapshot,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> ToolRuntimeResult:
        tool_name = snapshot.execution_spec.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            return _failure("invalid_mcp_tool", "MCP Tool is unavailable.")
        try:
            content, is_error = await call_mcp_tool(
                mcp_server_connection(self.server, self.settings),
                self.settings,
                tool_name,
                arguments,
                idempotency_key=context.idempotency_key,
            )
        except McpClientError:
            uncertain = snapshot.effect in {"external_write", "unknown"}
            return ToolRuntimeResult(
                ok=False,
                data=None,
                summary="MCP Tool request failed.",
                error_code="mcp_request_failed",
                error_message="MCP Tool request failed.",
                outcome="uncertain" if uncertain else "confirmed",
                usage={},
            )
        try:
            data: Any = json.loads(content)
        except json.JSONDecodeError:
            data = content
        return ToolRuntimeResult(
            ok=not is_error,
            data=data,
            summary="MCP Tool completed." if not is_error else "MCP Tool returned an error.",
            error_code="mcp_tool_error" if is_error else None,
            error_message="MCP Tool returned an error." if is_error else None,
            outcome="confirmed",
            usage={},
        )
