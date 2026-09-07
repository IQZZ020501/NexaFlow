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
                data={"iso8601": utc_now().astimezone(APP_TIMEZONE).isoformat()},
                summary="Current time returned.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )
        if builtin in {"artifact", "python_artifact", "skill"}:
            failure_code = {
                "artifact": "artifact_failed",
                "python_artifact": "python_artifact_failed",
                "skill": "skill_failed",
            }[builtin]
            try:
                filename = arguments["filename"]
                artifact_format = artifact_format_from_filename(filename)
                if builtin == "skill":
                    skill = snapshot.execution_spec.get("skill")
                    if not isinstance(skill, str):
                        raise ValueError("Skill Tool configuration is invalid.")
                    artifact = await execute_skill_artifact(
                        self.settings,
                        skill,
                        {
                            key: value
                            for key, value in arguments.items()
                            if key != "filename"
                        },
                        artifact_format,
                        filename,
                    )
                    artifact_content = artifact.content
                    artifact_stdout = artifact.stdout
                    artifact_exit_code = artifact.exit_code
                else:
                    supplied_format = arguments.get("format")
                    if (
                        supplied_format is not None
                        and supplied_format != artifact_format
                    ):
                        raise ValueError("Artifact format does not match its filename.")
                    content = arguments.get("content", arguments.get("code"))
                    if not isinstance(content, str):
                        raise TypeError
                    content_mode = arguments.get("content_mode")
                    if content_mode is not None and content_mode not in {
                        "text",
                        "python",
                    }:
                        raise ValueError(
                            "Artifact content_mode must be text or python."
                        )
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
                    skills = arguments.get("skills", [])
                    if (
                        not isinstance(skills, list)
                        or len(skills) > 8
                        or len(set(skills)) != len(skills)
                        or any(
                            not isinstance(skill, str)
                            or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", skill)
                            is None
                            for skill in skills
                        )
                    ):
                        raise ValueError("Artifact Tool skills are invalid.")
                    if direct_content:
                        artifact_content = content.encode("utf-8")
                        artifact_stdout = (
                            f"characters={len(content)}\nbytes={len(artifact_content)}"
                        )
                        artifact_exit_code = 0
                    else:
                        generator = _redirect_legacy_artifact_path(content, filename)
                        preflight_error = _artifact_code_preflight(
                            generator,
                            artifact_format,
                        )
                        if preflight_error is not None:
                            return _failure("artifact_code_invalid", preflight_error)
                        artifact = await execute_artifact_code(
                            self.settings,
                            generator,
                            artifact_format,
                            filename,
                            skills,
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
                arguments.get("skills"),
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
