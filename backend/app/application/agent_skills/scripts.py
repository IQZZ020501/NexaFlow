import json
import re
from pathlib import PurePosixPath

from app.application.agent_skills.dependencies import (
    dependency_install_plan,
    dependency_shell_request,
    skill_environment_id,
)
from app.application.agent_skills.execution import load_authorized_run_skill
from app.application.tools.runtime.contracts import ToolRuntimeResult
from app.domain.artifacts.services import artifact_format_from_filename
from app.infra.db.repositories.tools import repository as tool_repository
from app.infra.db.session import get_session_factory
from app.infra.sandbox.client import (
    WorkflowSandboxError,
    _artifact_result,
    _execution_fields,
)
from app.ports.execution import build_execution_platform


async def _installed_dependency_plans(db, workspace_id: str, run_id: str, version_id: str):
    from app.domain.tools.catalog.service import build_skill_dependency_installer_tool

    tool, _, _ = build_skill_dependency_installer_tool(workspace_id)
    invocations = await tool_repository.list_tool_invocations(
        db,
        workspace_id,
        run_id,
    )
    installed = []
    for invocation in reversed(invocations):
        if (
            invocation.tool_id != tool.id
            or invocation.status != "succeeded"
            or invocation.arguments.get("version_id") != version_id
        ):
            continue
        result = invocation.result_data
        if not isinstance(result, dict):
            raise WorkflowSandboxError("Stored dependency lock is invalid.")
        expected_hash = result.get("environment_hash")
        if not isinstance(expected_hash, str) or re.fullmatch(
            r"[a-f0-9]{64}", expected_hash
        ) is None:
            raise WorkflowSandboxError("Stored dependency lock is invalid.")
        plan = dependency_install_plan(
            invocation.arguments.get("manager"),
            invocation.arguments.get("packages"),
        )
        installed.append((plan, expected_hash))
    return installed


async def execute_skill_script(settings, arguments, context):
    snapshot = await load_authorized_run_skill(
        settings,
        context,
        arguments["version_id"],
    )
    async with get_session_factory()() as db:
        installed = await _installed_dependency_plans(
            db,
            context.workspace_id,
            context.run_id,
            snapshot.version_id,
        )
    path = arguments["path"]
    if path not in snapshot.definition.get("files", {}) or PurePosixPath(
        path
    ).suffix not in {".py", ".js"}:
        raise ValueError("Script is not in the pinned Skill package.")
    request = {
        "execution_session": "agent_run",
        "skill_environment": skill_environment_id(snapshot.version_id),
        "script": path,
        "files": snapshot.definition["files"],
        "stdin": json.dumps(arguments["inputs"], ensure_ascii=False),
        "limits": {
            "timeout_ms": round(
                snapshot.definition.get("execution_timeout_seconds", 30) * 1000
            )
        },
    }
    filename = arguments.get("filename")
    if filename:
        request["artifact"] = {
            "filename": filename,
            "format": artifact_format_from_filename(filename),
        }
    platform = build_execution_platform(settings)
    expected_hashes = {}
    replay_hashes = {}
    for plan, expected_hash in installed:
        expected_hashes[plan.manager] = expected_hash
        replay = await platform.execute(
            dependency_shell_request(snapshot, plan),
            timeout_seconds=snapshot.definition.get("execution_timeout_seconds", 30),
            max_output_bytes=256 * 1024,
        )
        _execution_fields(replay)
        replay_hashes[plan.manager] = replay.get("environment_hash")
    if replay_hashes != expected_hashes:
        await platform.close_session(context.workspace_id, context.run_id)
        raise WorkflowSandboxError(
            "Pinned Skill dependency environment could not be reproduced."
        )
    response = await platform.execute(
        request,
        timeout_seconds=snapshot.definition.get("execution_timeout_seconds", 30),
        max_output_bytes=8 * 1024 * 1024,
    )
    stdout, _, exit_code = _execution_fields(response)
    data = {"stdout": stdout, "exit_code": exit_code}
    if filename:
        from app.application.artifacts.service import create_generated_artifact

        artifact = _artifact_result(response, request["artifact"]["format"], filename)
        async with get_session_factory()() as db:
            link = await create_generated_artifact(
                db,
                settings,
                workspace_id=context.workspace_id,
                run_id=context.run_id,
                idempotency_key=context.idempotency_key,
                artifact_format=artifact.format,
                filename=filename,
                content=artifact.content,
            )
            await db.commit()
        data["artifacts"] = [
            {
                "artifact_id": link.artifact_id,
                "filename": link.filename,
                "format": link.format,
                "download_url": link.download_url,
                "size_bytes": link.size_bytes,
                "expires_at": link.expires_at.isoformat(),
                "mime_type": link.media_type,
            }
        ]
    return ToolRuntimeResult(
        ok=True,
        data=data,
        summary="Skill script completed.",
        error_code=None,
        error_message=None,
        outcome="confirmed",
        usage={"exit_code": exit_code},
    )
