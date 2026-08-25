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
from app.shareddomain.artifacts.services import artifact_format_from_filename
from app.shareddomain.tools.services import mcp_server_connection


DIRECT_ARTIFACT_CONTENT_FORMATS = frozenset(
    "file txt md markdown html htm css csv tsv json jsonl xml yaml yml toml "
    "ini cfg conf env py pyi ipynb java js jsx mjs cjs ts tsx c h cc cpp "
    "cxx hpp go rs rb php swift kt kts scala sh bash zsh fish ps1 sql "
    "graphql gql vue svelte dart lua r cs fs fsx vb gradle properties svg "
    "tex rtf log po pot".split()
)


def _is_direct_artifact_content(artifact_format: str, code: str) -> bool:
    return artifact_format in DIRECT_ARTIFACT_CONTENT_FORMATS and not (
        "output_path" in code or "NEXAFLOW_OUTPUT_PATH" in code
    )


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
                filename = arguments["filename"]
                artifact_format = artifact_format_from_filename(filename)
                supplied_format = arguments.get("format")
                if supplied_format is not None and supplied_format != artifact_format:
                    raise ValueError("Artifact format does not match its filename.")
                code = arguments["code"]
                if not isinstance(code, str):
                    raise TypeError
                if _is_direct_artifact_content(artifact_format, code):
                    artifact_content = code.encode("utf-8")
                    artifact_stdout = (
                        f"characters={len(code)}\nbytes={len(artifact_content)}"
                    )
                    artifact_exit_code = 0
                else:
                    artifact = await execute_artifact_code(
                        self.settings,
                        code,
                        artifact_format,
                        filename,
                        [],
                    )
                    artifact_content = artifact.content
                    artifact_stdout = artifact.stdout
                    artifact_exit_code = artifact.exit_code
            except WorkflowSandboxBusyError as exc:
                raise ToolAdapterBusy("Python sandbox is busy.") from exc
            except WorkflowSandboxError as exc:
                return _failure("python_artifact_failed", str(exc)[:1000])
            except (KeyError, TypeError, ValueError):
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
                        artifact_format=artifact_format,
                        filename=filename,
                        content=artifact_content,
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
                    "stdout": artifact_stdout.strip()[:2000],
                },
                summary="Artifact created.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={
                    "exit_code": artifact_exit_code,
                    "size_bytes": link.size_bytes,
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
