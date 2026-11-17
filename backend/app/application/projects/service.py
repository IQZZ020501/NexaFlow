"""Conversation-owned file trees backed by immutable file versions."""

import hashlib

from fastapi import HTTPException

from app.domain.projects.services import (
    MAX_PROJECT_HISTORY_BYTES,
    ProjectFileConflict,
    project_file_path,
    require_file_base,
    validate_project_tree,
)
from app.entities.defaults import utc_now
from app.entities.projects import AgentProject, ProjectFileVersion, ProjectRunState
from app.infra.db.repositories.projects import repository


async def require_project(db, workspace_id, project_id, owner_id, *, lock=False):
    project = await repository.get_project(db, project_id, lock=lock)
    if (
        project is None
        or project.workspace_id != workspace_id
        or project.created_by_user_id != owner_id
    ):
        raise HTTPException(404, "Project not found.")
    return project


async def save_changes(db, project, changes, *, run_id=None, invocation_id=None):
    """One project lock, all base-version checks, then one atomic revision.

    Changes contain immutable bytes or deletion tombstones. Nothing is written
    when any path conflicts, so independent workers never silently overwrite.
    """
    heads = {item.path: item for item in await repository.latest_files(db, project.id)}
    originals = dict(heads)
    created = []
    revision = project.revision + 1
    if len({item["path"] for item in changes}) != len(changes):
        raise ValueError("A project change may mention each path only once.")
    for change in changes:
        path, role = change["path"], change["role"]
        project_file_path(path, role)
        current = heads.get(path)
        content = change.get("content", b"")
        deleted = change.get("deleted", False)
        if not isinstance(content, bytes) or deleted and content:
            raise ValueError("Project file content is invalid.")
        if run_id and (role != "work" or current and current.role != "work"):
            raise ValueError("A Run cannot change source project files.")
        digest = hashlib.sha256(content).hexdigest()
        expected = change.get("expected_version_id")
        # Retrying an already accepted exact write does not append a version.
        if (
            current
            and current.previous_version_id == expected
            and current.role == role
            and current.deleted == deleted
            and current.content_hash == digest
        ):
            continue
        require_file_base(current, expected)
        if (
            current
            and current.content_hash == digest
            and current.deleted == deleted
            and current.role == role
        ):
            continue
        version = ProjectFileVersion(
            project_id=project.id,
            path=path,
            role=role,
            revision=revision,
            previous_version_id=current.id if current else None,
            deleted=deleted,
            content=content,
            content_hash=digest,
            size_bytes=len(content),
            run_id=run_id,
            invocation_id=invocation_id,
        )
        heads[path] = version
        created.append(version)
    validate_project_tree(list(heads.values()))
    if (
        await repository.history_bytes(db, project.id)
        + sum(item.size_bytes for item in created)
        > MAX_PROJECT_HISTORY_BYTES
    ):
        raise ValueError(
            "Conversation file history exceeds 256 MiB; start a new conversation with the necessary files."
        )
    for version in created:
        await repository.create_version(db, version)
    if created:
        project.revision = revision
        project.updated_at = utc_now()
        await repository.save_project(db, project)
    return heads, [item for path, item in heads.items() if originals.get(path) != item]


async def project_run_snapshot(db, workspace_id, project_id, owner_id):
    project = await require_project(db, workspace_id, project_id, owner_id, lock=True)
    files = await repository.latest_files(db, project_id)
    return {
        "schema_version": 1,
        "id": project.id,
        "name": project.name,
        "revision": project.revision,
        "owner_id": owner_id,
        "files": [
            {
                "version_id": item.id,
                "path": item.path,
                "role": item.role,
                "deleted": item.deleted,
                "sha256": item.content_hash,
                "size_bytes": item.size_bytes,
            }
            for item in files
        ],
    }


async def initialize_project_run(db, run):
    project = run.application_snapshot.get("project")
    if project:
        await repository.save_run_state(
            db,
            ProjectRunState(
                run_id=run.id,
                project_id=project["id"],
                file_heads={
                    item["path"]: item["version_id"] for item in project["files"]
                },
            ),
        )


async def conversation_run_snapshot(db, run, files=()):
    """Serialize against conversation deletion; consumers never supply a tree id."""
    from app.infra.db.repositories.agents import repository as runs

    agent = await runs.lock_agent(db, run.agent_id)
    if agent is None or agent.workspace_id != run.workspace_id:
        raise HTTPException(404, "Agent not found.")
    scope = [
        run.workspace_id,
        run.agent_id,
        run.access_source,
        run.consumer_id,
        run.conversation_id,
    ]
    previous = await runs.list_agent_runs(
        db,
        run.agent_id,
        run.access_source,
        run.consumer_id,
        limit=1,
        conversation_id=run.conversation_id,
        latest_versions_only=True,
    )
    frozen = previous[0].application_snapshot.get("project", {}) if previous else {}
    if frozen.get("conversation_scope"):
        if frozen["conversation_scope"] != scope:
            raise ValueError("Conversation file scope is invalid.")
        project = await require_project(
            db, run.workspace_id, frozen["id"], run.consumer_id, lock=True
        )
    else:
        project = await repository.save_project(
            db,
            AgentProject(
                workspace_id=run.workspace_id,
                created_by_user_id=run.consumer_id,
                name=run.conversation_id,
            ),
        )
        # Detach old manually shared projects on first use, preserving their bytes.
        if frozen:
            await require_project(db, run.workspace_id, frozen["id"], run.consumer_id)
            originals = []
            for item in await repository.latest_files(db, frozen["id"]):
                if not item.deleted:
                    version = await repository.get_version(db, frozen["id"], item.id)
                    originals.append(
                        {"path": item.path, "role": "work", "content": version.content}
                    )
            await save_changes(db, project, originals)
    heads = {item.path: item for item in await repository.latest_files(db, project.id)}
    try:
        await save_changes(
            db,
            project,
            [
                {
                    "path": item["path"],
                    "role": "work",
                    "content": item["content"],
                    "expected_version_id": heads[item["path"]].id
                    if item["path"] in heads
                    else None,
                }
                for item in files
            ],
        )
    except ProjectFileConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    snapshot = await project_run_snapshot(
        db, run.workspace_id, project.id, run.consumer_id
    )
    snapshot["conversation_scope"] = scope
    return snapshot


__all__ = [
    "conversation_run_snapshot",
    "initialize_project_run",
    "project_run_snapshot",
]
