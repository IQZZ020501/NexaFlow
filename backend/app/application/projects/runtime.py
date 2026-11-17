"""Lease-fenced project imports and immutable work-file checkpoints."""

import base64
import hashlib

from app.application.artifacts.service import create_generated_artifact
from app.application.projects.service import require_project, save_changes
from app.application.workspaces.service import build_workspace_context
from app.domain.projects.services import (
    MAX_PROJECT_BYTES,
    MAX_PROJECT_FILES,
    ProjectFileConflict,
    project_file_path,
)
from app.entities.defaults import utc_now
from app.infra.db.repositories.identity import users
from app.infra.db.repositories.projects import repository
from app.infra.db.session import get_session_factory
from app.ports.execution import (
    ExecutionError,
    ExecutionNotStarted,
    ExecutionOutcomeUnknown,
    execution_scope,
)


async def _authorized_project(db, run, *, lock=False):
    frozen = run.application_snapshot.get("project")
    if (
        not isinstance(frozen, dict)
        or frozen.get("owner_id") != run.execution_user_id
        or run.access_source != "console"
    ):
        raise ExecutionNotStarted("Project access is unavailable.")
    actor = await users.get_user_by_id(db, run.execution_user_id)
    if actor is None or not actor.is_active:
        raise ExecutionNotStarted("Project owner is no longer active.")
    await build_workspace_context(db, actor, run.workspace_id)
    return await require_project(
        db, run.workspace_id, frozen["id"], actor.id, lock=lock
    )


async def _cursor(db, run, project):
    state = await repository.get_run_state(db, run.id)
    if state is None or state.project_id != project.id:
        raise ExecutionError("Project checkpoint is unavailable.")
    return state


async def _versions(db, project, state):
    versions = {}
    for path, version_id in state.file_heads.items():
        version = await repository.get_version(db, project.id, version_id)
        if (
            version is None
            or version.path != path
            or hashlib.sha256(version.content).hexdigest() != version.content_hash
        ):
            raise ExecutionError("Project file checkpoint is invalid.")
        project_file_path(path, version.role)
        versions[path] = version
    return versions


async def restore_project_files(run, platform, *, timeout_seconds):
    if not run.application_snapshot.get("project"):
        return False
    async with get_session_factory()() as db:
        project = await _authorized_project(db, run)
        state = await _cursor(db, run, project)
        files = await _versions(db, project, state)
    for path, file in files.items():
        if file.deleted:
            continue
        # Guest staging is per path and per role; imports never replace edits
        # already made in that guest. A rebuilt guest receives this cursor.
        try:
            response = await platform.execute(
                {
                    "execution_session": "agent_run",
                    "restore_project_files": {
                        "project_id": project.id,
                        "role": file.role,
                        "files": {path: base64.b64encode(file.content).decode("ascii")},
                    },
                },
                timeout_seconds=timeout_seconds,
                max_output_bytes=4096,
            )
        except ExecutionOutcomeUnknown as exc:
            raise ExecutionNotStarted(
                "Project restoration failed before command execution."
            ) from exc
        if response.get("ok") is not True:
            raise ExecutionNotStarted("Project file could not be restored.")
    return True


def _manifest(response):
    items = response.get("project_changes")
    if (
        response.get("project_snapshot") is not True
        or not isinstance(items, list)
        or len(items) > MAX_PROJECT_FILES
    ):
        raise ValueError(
            str(response.get("project_error") or "Project snapshot is invalid.")[:300]
        )
    files = {}
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("relative_path"), str)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
            or type(item.get("size_bytes")) is not int
            or not 0 < item["size_bytes"] <= 5 * 1024 * 1024
            or item.get("deleted") is not False
        ):
            raise ValueError("Project snapshot is invalid.")
        path = project_file_path(item["relative_path"], "work")
        if path in files:
            raise ValueError("Project snapshot repeats a path.")
        files[path] = item
    if sum(item["size_bytes"] for item in files.values()) > MAX_PROJECT_BYTES:
        raise ValueError("Project exceeds 64 MiB.")
    return files


async def save_project_files(
    settings, run, context, platform, response, dependency_locks
):
    """Save only differences from this Run's cursor, in one project revision.

    A full guest snapshot allows an interrupted write to be retried safely.
    CAS uses the Run's base versions, never a freshly read project head.
    """
    if not run.application_snapshot.get("project"):
        return {}
    try:
        manifest = _manifest(response)
    except ValueError as exc:
        return {"project_saved": False, "project_error": str(exc)}
    async with get_session_factory()() as db:
        project = await _authorized_project(db, run)
        state = await _cursor(db, run, project)
        versions = await _versions(db, project, state)
    changes = []
    for path, item in manifest.items():
        previous = versions.get(path)
        if previous and previous.role != "work":
            return {
                "project_saved": False,
                "project_error": "A work file conflicts with a source path; rename the work file.",
            }
        if (
            previous
            and not previous.deleted
            and previous.content_hash == item["sha256"]
        ):
            continue
        content = await platform.read_session_file(
            context.workspace_id, context.run_id, item["path"], 5 * 1024 * 1024
        )
        if (
            len(content) != item["size_bytes"]
            or hashlib.sha256(content).hexdigest() != item["sha256"]
        ):
            raise ExecutionError("Project export content changed.")
        changes.append(
            {
                "path": path,
                "role": "work",
                "content": content,
                "expected_version_id": previous.id if previous else None,
            }
        )
    changes.extend(
        {"path": path, "role": "work", "deleted": True, "expected_version_id": file.id}
        for path, file in versions.items()
        if file.role == "work" and not file.deleted and path not in manifest
    )
    scope = execution_scope.get()
    async with get_session_factory()() as db:
        if (
            scope is None
            or scope.run_id != run.id
            or not scope.worker_task_id
            or not await repository.lock_run_writer(
                db, run.id, scope.worker_task_id, utc_now()
            )
        ):
            raise ExecutionError(
                "Project save rejected because the Run lease was lost."
            )
        project = await _authorized_project(db, run, lock=True)
        current_state = await _cursor(db, run, project)
        if current_state.file_heads != state.file_heads:
            raise ExecutionError("Project Run checkpoint changed during execution.")
        try:
            heads, saved = await save_changes(
                db, project, changes, run_id=run.id, invocation_id=context.invocation_id
            )
        except (ProjectFileConflict, ValueError) as exc:
            # Keep recovery bytes as immutable Run artifacts; never silently
            # replace another Run's project version. Deletions remain explicit.
            conflicts = []
            for change in changes:
                if change.get("deleted"):
                    conflicts.append({"relative_path": change["path"], "deleted": True})
                    continue
                digest = hashlib.sha256(change["content"]).hexdigest()
                filename = f"project-conflict-{digest[:16]}.bin"
                link = await create_generated_artifact(
                    db,
                    settings,
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    idempotency_key=hashlib.sha256(
                        f"project-conflict:{context.idempotency_key}:{change['path']}".encode()
                    ).hexdigest(),
                    artifact_format="bin",
                    filename=filename,
                    content=change["content"],
                    invocation_id=context.invocation_id,
                )
                conflicts.append(
                    {
                        "relative_path": change["path"],
                        "artifact_id": link.artifact_id,
                        "filename": link.filename,
                        "format": "bin",
                        "content_hash": link.content_hash,
                        "download_url": link.download_url,
                        "size_bytes": link.size_bytes,
                    }
                )
            await db.commit()
            return {
                "project_saved": False,
                "project_error": str(exc),
                "project_conflicts": conflicts,
            }
        accepted = [heads[change["path"]] for change in changes]
        current_state.file_heads = {
            **current_state.file_heads,
            **{item.path: item.id for item in accepted},
        }
        current_state.dependency_locks = dependency_locks
        current_state.updated_at = utc_now()
        await repository.save_run_state(db, current_state)
        await db.commit()
    return {
        "project_saved": True,
        "project_id": project.id,
        "project_revision": project.revision,
        "project_files": [
            {
                "path": item.path,
                "version_id": item.id,
                "sha256": item.content_hash,
                "deleted": item.deleted,
            }
            for item in saved
        ],
    }
