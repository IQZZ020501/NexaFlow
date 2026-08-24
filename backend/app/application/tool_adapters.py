"""Provider adapters behind the unified Tool runtime contract."""

import json
from typing import Any

from app.application.artifacts import create_generated_artifact
from app.entities.tools import McpServer, ToolSnapshot
from app.infrastructure.code_sandbox import (
    WorkflowSandboxBusyError,
    WorkflowSandboxError,
    execute_artifact_code,
    execute_workflow_code,
)
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.session import get_session_factory
from app.ports.mcp import McpClientError, call_mcp_tool
from app.ports.tool_runtime import (
    ToolAdapter,
    ToolAdapterBusy,
    ToolInvocationContext,
    ToolRuntimeResult,
)
from app.shareddomain.tools.services import mcp_server_connection


class BuiltinToolAdapter:
    kind = "builtin"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def invoke(
        self,
        snapshot: ToolSnapshot,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> ToolRuntimeResult:
        builtin = snapshot.execution_spec.get("builtin")
        if builtin == "current_time":
            return ToolRuntimeResult(
                ok=True,
                data={"iso8601": utc_now().isoformat()},
                summary="Current UTC time returned.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )
        if builtin == "python_artifact":
            try:
                artifact = await execute_artifact_code(
                    self.settings,
                    arguments["code"],
                    arguments["format"],
                    arguments["filename"],
                    arguments.get("skills", []),
                )
            except WorkflowSandboxBusyError as exc:
                raise ToolAdapterBusy("Python sandbox is busy.") from exc
            except WorkflowSandboxError as exc:
                return _failure("python_artifact_failed", str(exc)[:1000])
            except (KeyError, TypeError):
                return _failure(
                    "python_artifact_failed",
                    "Artifact Tool parameters are invalid.",
                )
            try:
                async with get_session_factory()() as db:
                    link = await create_generated_artifact(
                        db,
                        self.settings,
                        workspace_id=context.workspace_id,
                        run_id=context.run_id,
                        idempotency_key=context.idempotency_key,
                        artifact_format=artifact.format,
                        filename=artifact.filename,
                        content=artifact.content,
                    )
                    await db.commit()
            except ValueError as exc:
                return _failure("python_artifact_failed", str(exc)[:1000])
            return ToolRuntimeResult(
                ok=True,
                data={
                    "artifact_id": link.artifact_id,
                    "format": link.format,
                    "filename": link.filename,
                    "download_url": link.download_url,
                    "expires_at": link.expires_at.isoformat(),
                    "size_bytes": link.size_bytes,
                },
                summary="Artifact created.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={
                    "exit_code": artifact.exit_code,
                    "size_bytes": artifact.size_bytes,
                },
            )
        if builtin != "inline_python" or context.origin != "workflow":
            return _failure("unsupported_builtin", "Built-in Tool is unavailable.")
        try:
            result = await execute_workflow_code(
                self.settings,
                arguments["code"],
                arguments["inputs"],
            )
        except WorkflowSandboxBusyError as exc:
            raise ToolAdapterBusy("Python sandbox is busy.") from exc
        except (KeyError, TypeError, WorkflowSandboxError):
            return _failure("python_execution_failed", "Python Tool execution failed.")
        return ToolRuntimeResult(
            ok=True,
            data={"result": result.result},
            summary="Python Tool completed.",
            error_code=None,
            error_message=None,
            outcome="confirmed",
            usage={"exit_code": result.exit_code},
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
            result = await execute_workflow_code(self.settings, code, arguments)
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


def _failure(code: str, message: str) -> ToolRuntimeResult:
    return ToolRuntimeResult(
        ok=False,
        data=None,
        summary=message,
        error_code=code,
        error_message=message,
        outcome="confirmed",
        usage={},
    )


__all__ = [
    "BuiltinToolAdapter",
    "McpToolAdapter",
    "PythonToolAdapter",
    "build_tool_adapter",
]
