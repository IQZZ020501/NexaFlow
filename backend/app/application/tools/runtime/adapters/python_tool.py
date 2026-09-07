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

class PythonToolAdapter:
    kind = "python"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def invoke(
        self,
        snapshot: ToolSnapshot,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> ToolRuntimeResult:
        del context
        code = snapshot.execution_spec.get("code")
        if not isinstance(code, str):
            return _failure("invalid_python_tool", "Python Tool code is unavailable.")
        try:
            skills = arguments.get("skills")
            result = await execute_workflow_code(
                self.settings,
                code,
                arguments,
                skills if isinstance(skills, list) else None,
            )
        except WorkflowSandboxBusyError as exc:
            raise ToolAdapterBusy("Python sandbox is busy.") from exc
        except WorkflowSandboxError:
            return _failure(
                "python_execution_failed",
                "Python Tool execution failed.",
            )
        return ToolRuntimeResult(
            ok=True,
            data=result.result,
            summary="Python Tool completed.",
            error_code=None,
            error_message=None,
            outcome="confirmed",
            usage={"exit_code": result.exit_code},
        )
