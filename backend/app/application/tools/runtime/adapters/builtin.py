"""Provider adapters behind the unified Tool runtime contract."""

import re
from typing import Any

from app.application.artifacts.service import create_generated_artifact
from app.application.tools.runtime.adapters._common import (
    DIRECT_ARTIFACT_CONTENT_FORMATS,
    _artifact_code_preflight,
    _artifact_error_message,
    _failure,
    _is_direct_artifact_content,
    _redirect_legacy_artifact_path,
)
from app.domain.artifacts.services import artifact_format_from_filename
from app.entities.tools import ToolKind, ToolSnapshot
from app.infra.config.settings import Settings
from app.infra.db.session import get_session_factory
from app.infra.sandbox.client import (
    WorkflowSandboxBusyError,
    WorkflowSandboxError,
    execute_artifact_code,
    execute_skill_artifact,
)
from app.ports.execution import ExecutionBusy, ExecutionError, ExecutionOutcomeUnknown
from app.ports.llm import ModelProviderError, ModelProviderStatusError
from app.ports.tools import (
    ToolAdapterBusy,
    ToolInvocationContext,
    ToolRuntimeResult,
)


class BuiltinToolAdapter:
    kind: ToolKind = "builtin"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def invoke(
        self,
        snapshot: ToolSnapshot,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> ToolRuntimeResult:
        builtin = snapshot.execution_spec.get("builtin")
        if builtin == "skill_guide":
            from app.domain.tools.catalog.guides import BUILTIN_GUIDE_NAMES

            skill = snapshot.execution_spec.get("skill")
            instructions = snapshot.execution_spec.get("instructions")
            if (
                not isinstance(skill, str)
                or skill not in BUILTIN_GUIDE_NAMES
                or not isinstance(instructions, str)
                or not instructions.strip()
                or len(instructions.encode("utf-8")) > 16_000
            ):
                return _failure(
                    "skill_guide_invalid", "Skill instructions are unavailable."
                )
            return ToolRuntimeResult(
                ok=True,
                data={"skill": skill, "instructions": instructions},
                summary="Skill loaded. Follow its instructions using authorized bash.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )
        if builtin == "shell":
            from app.application.tools.runtime.adapters.shell import execute_shell
            try:
                return await execute_shell(self.settings, arguments, context)
            except ExecutionBusy as exc:
                raise ToolAdapterBusy("Command runtime is busy.") from exc
            except ExecutionOutcomeUnknown as exc:
                return _failure("shell_failed", str(exc)[:1000], uncertain=True)
            except (ValueError, ExecutionError, OSError, TimeoutError) as exc:
                return _failure("shell_failed", str(exc)[:1000])
        if builtin == "image_generation":
            from app.application.tools.runtime.adapters.image_generation import (
                generate_image_artifact,
            )

            try:
                return await generate_image_artifact(self.settings, arguments, context)
            except (KeyError, TypeError, ValueError) as exc:
                return _failure("image_generation_unavailable", str(exc)[:1000])
            except ModelProviderError as exc:
                message = (
                    f"Image provider returned status {exc.status_code}."
                    if isinstance(exc, ModelProviderStatusError)
                    else "Image generation failed or returned an unusable image."
                )
                uncertain = not isinstance(exc, ModelProviderStatusError) or exc.status_code >= 500
                return ToolRuntimeResult(
                    ok=False, data=None, summary=message,
                    error_code="image_generation_failed", error_message=message,
                    outcome="uncertain" if uncertain else "confirmed", usage={},
                )
        if builtin == "skill_script":
            from app.application.agent_skills.scripts import execute_skill_script

            try:
                return await execute_skill_script(self.settings, arguments, context)
            except ExecutionBusy as exc:
                raise ToolAdapterBusy("Skill runtime is busy.") from exc
            except ExecutionOutcomeUnknown as exc:
                return _failure("skill_script_failed", str(exc)[:1000], uncertain=True)
            except (ValueError, WorkflowSandboxError) as exc:
                return _failure("skill_script_failed", str(exc)[:1000])
        if builtin == "skill_dependency_install":
            from app.application.agent_skills.dependencies import (
                execute_skill_dependency_install,
            )

            try:
                return await execute_skill_dependency_install(
                    self.settings,
                    arguments,
                    context,
                )
            except ExecutionBusy as exc:
                raise ToolAdapterBusy("Skill runtime is busy.") from exc
            except ExecutionOutcomeUnknown as exc:
                return _failure("skill_dependency_install_failed", str(exc)[:1000], uncertain=True)
            except (ValueError, WorkflowSandboxError) as exc:
                return _failure("skill_dependency_install_failed", str(exc)[:1000])
        if builtin in {"artifact", "python_artifact", "skill"}:
            failure_code = {
                "artifact": "artifact_failed",
                "python_artifact": "python_artifact_failed",
                "skill": "skill_failed",
            }[builtin]
            artifact_inspection = {}
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
                    artifact_inspection = artifact.inspection
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
                            or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", skill) is None
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
                        artifact_inspection = artifact.inspection
            except WorkflowSandboxBusyError as exc:
                raise ToolAdapterBusy("File runtime is busy.") from exc
            except ExecutionOutcomeUnknown as exc:
                return _failure(failure_code, str(exc)[:1000], uncertain=True)
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
                        invocation_id=context.invocation_id,
                        inspection=artifact_inspection,
                    )
                    await db.commit()
            except ValueError as exc:
                return _failure(failure_code, str(exc)[:1000])
            artifact_data = {
                "artifact_id": link.artifact_id,
                "format": link.format,
                "filename": link.filename,
                "relative_path": link.relative_path,
                "content_hash": link.content_hash,
                "previous_artifact_id": link.previous_artifact_id,
                "inspection": link.inspection,
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
            if (
                snapshot.output_schema
                and snapshot.output_schema.get("additionalProperties") is False
            ):
                result_data = {
                    key: value
                    for key, value in result_data.items()
                    if key in output_properties
                }
            if isinstance(output_properties, dict) and "artifacts" in output_properties:
                artifact_data["mime_type"] = link.media_type
                item_schema = output_properties["artifacts"].get("items", {})
                if item_schema.get("additionalProperties") is False:
                    artifact_data = {
                        key: value
                        for key, value in artifact_data.items()
                        if key in item_schema.get("properties", {})
                    }
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
        return _failure("unsupported_builtin", "Built-in Tool is unavailable.")
