"""Provider adapters behind the unified Tool runtime contract."""

from typing import Any

from app.application.tools.runtime.adapters._common import (  # noqa: F401
    _UNAVAILABLE_ARTIFACT_IMPORTS,
    DIRECT_ARTIFACT_CONTENT_FORMATS,
    _artifact_code_preflight,
    _artifact_error_message,
    _failure,
    _is_direct_artifact_content,
    _redirect_legacy_artifact_path,
)
from app.application.tools.runtime.contracts import (
    ToolAdapterBusy,
    ToolInvocationContext,
    ToolRuntimeResult,
)
from app.entities.tools import ToolSnapshot
from app.infra.config.settings import Settings
from app.infra.sandbox.client import (
    WorkflowSandboxBusyError,
    WorkflowSandboxError,
    execute_workflow_code,
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
