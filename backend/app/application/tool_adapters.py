"""Provider adapters behind the unified Tool runtime contract."""

import ast
import json
import re
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


def _redirect_legacy_artifact_path(code: str, filename: str) -> str:
    """Repair the legacy model pattern that saves the requested file under /tmp."""

    escaped_filename = re.escape(filename)
    return re.sub(
        rf"(['\"])/tmp/[^'\"\n]*{escaped_filename}\1",
        "output_path",
        code,
    )


_UNAVAILABLE_ARTIFACT_IMPORTS = {
    "reportlab": (
        "PDF generation uses PyMuPDF in this runtime: import pymupdf. "
        "reportlab is not installed."
    ),
    "fpdf": (
        "PDF generation uses PyMuPDF in this runtime: import pymupdf. "
        "fpdf is not installed."
    ),
    "weasyprint": (
        "PDF generation uses PyMuPDF in this runtime: import pymupdf. "
        "weasyprint is not installed."
    ),
}


def _artifact_code_preflight(code: str, artifact_format: str) -> str | None:
    try:
        tree = ast.parse(code, filename="<artifact-tool>")
    except SyntaxError as exc:
        location = f"line {exc.lineno}" if exc.lineno else "the submitted code"
        return f"Artifact generator has a syntax error at {location}: {exc.msg}."

    imported_modules: set[str] = set()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".", 1)[0])
                imported_names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".", 1)[0])
            imported_names.update(alias.asname or alias.name for alias in node.names)

    for module, message in _UNAVAILABLE_ARTIFACT_IMPORTS.items():
        if module in imported_modules:
            return (
                f"{message} Do not repeat the same generator code; replace that "
                "import and retry."
            )

    if artifact_format == "pdf":
        references_fitz = any(
            isinstance(node, ast.Name) and node.id == "fitz"
            for node in ast.walk(tree)
        )
        if references_fitz and "fitz" not in imported_names:
            return (
                "PDF generator references 'fitz' without importing it. Add "
                "'import pymupdf as fitz' at the top, then retry once; do not "
                "repeat the same code."
            )
    return None


def _artifact_error_message(error: Exception) -> str:
    message = str(error).strip()
    for line in reversed(message.splitlines()):
        candidate = line.strip()
        if re.match(
            r"(?:ModuleNotFoundError|ImportError|NameError|SyntaxError|"
            r"PermissionError|RuntimeError|ValueError|TypeError):",
            candidate,
        ):
            return candidate[:1000]
    return message[:1000]


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
        if builtin in {"artifact", "python_artifact"}:
            failure_code = (
                "artifact_failed"
                if builtin == "artifact"
                else "python_artifact_failed"
            )
            try:
                filename = arguments["filename"]
                artifact_format = artifact_format_from_filename(filename)
                supplied_format = arguments.get("format")
                if supplied_format is not None and supplied_format != artifact_format:
                    raise ValueError("Artifact format does not match its filename.")
                content = arguments.get("content", arguments.get("code"))
                if not isinstance(content, str):
                    raise TypeError
                content_mode = arguments.get("content_mode")
                if content_mode is not None and content_mode not in {"text", "python"}:
                    raise ValueError("Artifact content_mode must be text or python.")
                direct_content = (
                    artifact_format in DIRECT_ARTIFACT_CONTENT_FORMATS
                    if content_mode == "text"
                    else content_mode != "python"
                    and _is_direct_artifact_content(artifact_format, content)
                )
                if content_mode == "text" and not direct_content:
                    raise ValueError(
                        "Rich and binary files require content_mode=python."
                    )
                if direct_content:
                    artifact_content = content.encode("utf-8")
                    artifact_stdout = (
                        f"characters={len(content)}\nbytes={len(artifact_content)}"
                    )
                    artifact_exit_code = 0
                else:
                    generator = _redirect_legacy_artifact_path(content, filename)
                    preflight_error = _artifact_code_preflight(generator, artifact_format)
                    if preflight_error is not None:
                        return _failure("artifact_code_invalid", preflight_error)
                    artifact = await execute_artifact_code(
                        self.settings,
                        generator,
                        artifact_format,
                        filename,
                        [],
                    )
                    artifact_content = artifact.content
                    artifact_stdout = artifact.stdout
                    artifact_exit_code = artifact.exit_code
            except WorkflowSandboxBusyError as exc:
                raise ToolAdapterBusy("File runtime is busy.") from exc
            except WorkflowSandboxError as exc:
                return _failure(failure_code, _artifact_error_message(exc))
            except (KeyError, TypeError):
                return _failure(
                    failure_code,
                    "Artifact Tool parameters are invalid.",
                )
            except ValueError as exc:
                return _failure(failure_code, str(exc)[:1000])
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
                return _failure(failure_code, str(exc)[:1000])
            artifact_data = {
                "artifact_id": link.artifact_id,
                "format": link.format,
                "filename": link.filename,
                "download_url": link.download_url,
                "expires_at": link.expires_at.isoformat(),
                "size_bytes": link.size_bytes,
            }
            result_data = {
                **artifact_data,
                "stdout": artifact_stdout.strip()[:2000],
            }
            output_properties = (
                snapshot.output_schema.get("properties", {})
                if isinstance(snapshot.output_schema, dict)
                else {}
            )
            if isinstance(output_properties, dict) and "artifacts" in output_properties:
                artifact_data["mime_type"] = link.media_type
                result_data["artifacts"] = [artifact_data]
            return ToolRuntimeResult(
                ok=True,
                data=result_data,
                summary="File created.",
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
