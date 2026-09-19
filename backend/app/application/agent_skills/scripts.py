import json
from pathlib import PurePosixPath

from app.application.agent_skills.execution import require_pinned_skill_access
from app.application.tools.runtime.contracts import ToolRuntimeResult
from app.domain.agent_skills.contracts import agent_skill_snapshot_from_payload
from app.domain.agents.models import AGENT_RUN_RUNNING_STATUSES
from app.domain.artifacts.services import artifact_format_from_filename
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.session import get_session_factory
from app.infra.execution.profile import require_execution_profile
from app.infra.sandbox.client import _artifact_result, _execution_fields
from app.ports.execution import build_execution_platform


async def execute_skill_script(settings, arguments, context):
    async with get_session_factory()() as db:
        run = (
            await runs.get_agent_run_by_id(db, context.run_id)
            if context.run_id
            else None
        )
        if (
            run is None
            or run.workspace_id != context.workspace_id
            or run.execution_user_id != context.execution_user_id
            or run.status not in AGENT_RUN_RUNNING_STATUSES
        ):
            raise ValueError("Skill script requires its authorized Agent run.")
        require_execution_profile(
            settings, run.application_snapshot.get("execution_profile")
        )
        snapshot = next(
            (
                agent_skill_snapshot_from_payload(item)
                for item in run.skill_snapshots
                if item.get("version_id") == arguments["version_id"]
            ),
            None,
        )
        if snapshot is None:
            raise ValueError("Skill is not in the run's pinned catalog.")
        # A script tool is not a harness_internal action. Unified invocation
        # authorization/ledger already ran; package ACL is checked here too.
        await require_pinned_skill_access(db, context.workspace_id, snapshot)
    path = arguments["path"]
    if path not in snapshot.definition.get("files", {}) or PurePosixPath(
        path
    ).suffix not in {".py", ".js"}:
        raise ValueError("Script is not in the pinned Skill package.")
    request = {
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
    response = await build_execution_platform(settings).execute(
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
