"""Ledger-backed bash results and streamed, idempotent generated artifacts."""

import hashlib
from datetime import UTC

from app.application.agent_skills.execution import require_pinned_skill_access
from app.application.agent_skills.scripts import (
    _installed_dependency_plans,
    restore_skill_dependencies,
)
from app.application.artifacts.service import create_generated_artifact
from app.application.artifacts.workspace import restore_conversation_files
from app.application.tools.runtime.contracts import ToolRuntimeResult
from app.domain.agent_skills.contracts import agent_skill_snapshot_from_payload
from app.domain.agent_skills.paths import skill_mount_name
from app.domain.agents.models import AGENT_RUN_RUNNING_STATUSES
from app.domain.artifacts.services import artifact_format_from_filename
from app.entities.defaults import utc_now
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.session import get_session_factory
from app.ports.execution import ExecutionError, build_execution_platform


async def execute_shell(settings, arguments, context):
    if not context.run_id or context.origin != "agent":
        raise ValueError("Command execution requires an authorized Agent Run.")
    mounts = {}
    dependencies = []
    async with get_session_factory()() as db:
        run = await runs.get_agent_run_by_id(db, context.run_id)
        if (
            not run
            or run.workspace_id != context.workspace_id
            or run.execution_user_id != context.execution_user_id
            or run.access_source != context.access_source
            or run.status not in AGENT_RUN_RUNNING_STATUSES
        ):
            raise ValueError("Command execution requires an active authorized Run.")
        for payload in run.skill_snapshots:
            skill = agent_skill_snapshot_from_payload(payload)
            await require_pinned_skill_access(db, context.workspace_id, skill)
            mounts[skill_mount_name(skill.name, skill.version_id)] = (
                skill.definition.get("files", {})
            )
            dependencies.append(
                (
                    skill,
                    await _installed_dependency_plans(
                        db, context.workspace_id, context.run_id, skill.version_id
                    ),
                )
            )
    seconds = arguments.get("timeout_seconds", 60)
    if type(seconds) is not int or not 1 <= seconds <= 300:
        raise ValueError("Command timeout must be between 1 and 300 seconds.")
    deadline = (
        context.deadline_at.replace(tzinfo=UTC)
        if context.deadline_at.tzinfo is None
        else context.deadline_at
    )
    seconds = min(seconds, int((deadline - utc_now()).total_seconds()) - 5)
    if seconds < 1:
        raise ValueError("Command deadline expired.")
    platform = build_execution_platform(settings)
    reset = False
    for skill, installed in dependencies:
        reset = (
            await restore_skill_dependencies(skill, installed, context, platform)
            or reset
        )
    await restore_conversation_files(run, platform, timeout_seconds=seconds + 10)
    response = await platform.execute(
        {
            "execution_session": "agent_run",
            "command": {"command": arguments["command"], "timeout_seconds": seconds},
            "skill_mounts": mounts,
        },
        timeout_seconds=seconds + 10,
        max_output_bytes=256 * 1024,
    )
    if response.get("ok") is not True or type(response.get("exit_code")) is not int:
        raise ExecutionError(
            str(response.get("error") or "Command sandbox failed.")[:1000]
        )
    artifacts = []
    manifest = response.get("artifacts", [])
    if not isinstance(manifest, list) or len(manifest) > 8:
        raise ExecutionError("Invalid command artifact manifest.")
    warnings = list(response.get("warnings", []))[:16]
    for item in manifest:
        if (
            not isinstance(item, dict)
            or any(
                not isinstance(item.get(key), str)
                for key in ("path", "relative_path", "filename", "sha256")
            )
            or type(item.get("size_bytes")) is not int
            or not 0 < item["size_bytes"] <= 5 * 1024 * 1024
        ):
            raise ExecutionError("Invalid command artifact manifest.")
        content = await platform.read_session_file(
            context.workspace_id, context.run_id, item["path"], 5 * 1024 * 1024
        )
        if len(content) != item.get("size_bytes") or hashlib.sha256(
            content
        ).hexdigest() != item.get("sha256"):
            raise ExecutionError("Command artifact content changed.")
        try:
            filename = item["filename"]
            artifact_format = artifact_format_from_filename(filename)
            key = hashlib.sha256(
                f"{context.idempotency_key}:{item['relative_path']}".encode()
            ).hexdigest()
            async with get_session_factory()() as db:
                link = await create_generated_artifact(
                    db,
                    settings,
                    workspace_id=context.workspace_id,
                    run_id=context.run_id,
                    idempotency_key=key,
                    artifact_format=artifact_format,
                    filename=filename,
                    relative_path=item["relative_path"],
                    content=content,
                )
                await db.commit()
        except ValueError as exc:
            warnings.append(f"Output omitted: {str(exc)[:200]}")
            continue
        artifacts.append(
            {
                "artifact_id": link.artifact_id,
                "filename": link.filename,
                "format": link.format,
                "download_url": link.download_url,
                "size_bytes": link.size_bytes,
                "expires_at": link.expires_at.isoformat(),
                "mime_type": link.media_type,
            }
        )
    data = {
        key: response.get(key)
        for key in (
            "stdout",
            "stderr",
            "exit_code",
            "timed_out",
            "truncated",
            "workspace_reset",
        )
    }
    if reset:
        data["workspace_reset"] = True
    data.update(artifacts=artifacts, warnings=warnings[:16])
    return ToolRuntimeResult(
        ok=True,
        data=data,
        summary=f"Command exited with status {response['exit_code']}.",
        error_code=None,
        error_message=None,
        outcome="confirmed",
        usage={"exit_code": response["exit_code"]},
    )
