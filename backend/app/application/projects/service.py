import hashlib
from dataclasses import replace

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
from app.infra.runtime.validation import normalize_name
from app.schemas.projects import ProjectFileResponse, ProjectResponse


async def require_project(db, workspace_id, project_id, owner_id, *, lock=False):
    project = await repository.get_project(db, project_id, lock=lock)
    if (
        project is None
        or project.workspace_id != workspace_id
        or project.created_by_user_id != owner_id
    ):
        raise HTTPException(404, "Project not found.")
    return project


async def list_projects(db, workspace_id, owner_id, limit=100, offset=0):
    return [
        ProjectResponse.model_validate(item)
        for item in await repository.list_projects(
            db, workspace_id, owner_id, limit, offset
        )
    ]


async def create_project(db, workspace_id, owner_id, name):
    project = await repository.save_project(
        db,
        AgentProject(
            workspace_id=workspace_id,
            created_by_user_id=owner_id,
            name=normalize_name(name),
        ),
    )
    await db.commit()
    return ProjectResponse.model_validate(project)


async def rename_project(db, workspace_id, project_id, owner_id, name):
    project = await require_project(db, workspace_id, project_id, owner_id, lock=True)
    project.name = normalize_name(name)
    project.updated_at = utc_now()
    await repository.save_project(db, project)
    await db.commit()
    return ProjectResponse.model_validate(project)


async def delete_project(db, workspace_id, project_id, owner_id):
    project = await require_project(db, workspace_id, project_id, owner_id, lock=True)
    if await repository.has_active_runs(db, project.id):
        raise HTTPException(
            409, "Project has an active Run; stop it before deleting the project."
        )
    await repository.delete_project(db, project)
    await db.commit()


async def list_files(db, workspace_id, project_id, owner_id):
    await require_project(db, workspace_id, project_id, owner_id)
    return [
        ProjectFileResponse.model_validate(item)
        for item in await repository.latest_files(db, project_id)
    ]


async def get_file(db, workspace_id, project_id, owner_id, version_id):
    await require_project(db, workspace_id, project_id, owner_id)
    version = await repository.get_version(db, project_id, version_id)
    if version is None or version.deleted:
        raise HTTPException(404, "Project file not found.")
    return version


async def list_versions(db, workspace_id, project_id, owner_id, path, limit, offset):
    await require_project(db, workspace_id, project_id, owner_id)
    try:
        project_file_path(path, "source")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return [
        ProjectFileResponse.model_validate(item)
        for item in await repository.list_versions(db, project_id, path, limit, offset)
    ]


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
            "Project history exceeds 256 MiB; retain necessary files in a new project."
        )
    for version in created:
        await repository.create_version(db, version)
    if created:
        project.revision = revision
        project.updated_at = utc_now()
        await repository.save_project(db, project)
    return heads, [item for path, item in heads.items() if originals.get(path) != item]


async def put_file(
    db, workspace_id, project_id, owner_id, path, role, content, expected_version_id
):
    project = await require_project(db, workspace_id, project_id, owner_id, lock=True)
    try:
        heads, _ = await save_changes(
            db,
            project,
            [
                {
                    "path": path,
                    "role": role,
                    "content": content,
                    "expected_version_id": expected_version_id,
                }
            ],
        )
    except ProjectFileConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.commit()
    return ProjectFileResponse.model_validate(heads[path])


async def delete_file(
    db, workspace_id, project_id, owner_id, path, expected_version_id
):
    project = await require_project(db, workspace_id, project_id, owner_id, lock=True)
    heads = {item.path: item for item in await repository.latest_files(db, project_id)}
    current = heads.get(path)
    if current is None:
        raise HTTPException(404, "Project file not found.")
    try:
        heads, _ = await save_changes(
            db,
            project,
            [
                {
                    "path": path,
                    "role": current.role,
                    "deleted": True,
                    "expected_version_id": expected_version_id,
                }
            ],
        )
    except ProjectFileConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    return ProjectFileResponse.model_validate(heads[path])


async def rename_file(
    db, workspace_id, project_id, owner_id, path, new_path, expected_version_id
):
    project = await require_project(db, workspace_id, project_id, owner_id, lock=True)
    heads = {item.path: item for item in await repository.latest_files(db, project_id)}
    current = heads.get(path)
    target = heads.get(new_path)
    if current is None:
        raise HTTPException(404, "Project file not found.")
    if (
        current.deleted
        and current.previous_version_id == expected_version_id
        and target
        and not target.deleted
        and target.previous_version_id == expected_version_id
    ):
        return ProjectFileResponse.model_validate(target)
    try:
        require_file_base(current, expected_version_id)
        project_file_path(new_path, current.role)
        if path == new_path:
            return ProjectFileResponse.model_validate(current)
        if current.deleted or target and not target.deleted:
            raise ProjectFileConflict("Rename target exists or the source was deleted.")
        source = await repository.get_version(db, project_id, current.id)
        target_version = replace(
            source,
            id=ProjectFileVersion().id,
            path=new_path,
            revision=project.revision + 1,
            previous_version_id=source.id,
            created_at=utc_now(),
        )
        tombstone = ProjectFileVersion(
            project_id=project.id,
            path=path,
            role=current.role,
            revision=project.revision + 1,
            previous_version_id=current.id,
            deleted=True,
            content_hash=hashlib.sha256(b"").hexdigest(),
        )
        heads[path], heads[new_path] = tombstone, target_version
        validate_project_tree(list(heads.values()))
        if (
            await repository.history_bytes(db, project_id) + source.size_bytes
            > MAX_PROJECT_HISTORY_BYTES
        ):
            raise ValueError("Project history exceeds 256 MiB.")
        await repository.create_version(db, tombstone)
        await repository.create_version(db, target_version)
        project.revision += 1
        project.updated_at = utc_now()
        await repository.save_project(db, project)
    except ProjectFileConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.commit()
    return ProjectFileResponse.model_validate(target_version)


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


async def resolve_conversation_project(
    db, workspace_id, agent_id, owner_id, conversation_id, project_id
):
    from app.infra.db.repositories.agents import repository as runs

    if conversation_id:
        previous = await runs.list_agent_runs(
            db,
            agent_id,
            "console",
            owner_id,
            limit=1,
            conversation_id=conversation_id,
            latest_versions_only=True,
        )
        if previous:
            bound = previous[0].application_snapshot.get("project", {}).get("id")
            if project_id is not None and project_id != bound:
                raise HTTPException(
                    409, "Start a new conversation before changing its project."
                )
            project_id = bound
    if project_id:
        await require_project(db, workspace_id, project_id, owner_id)
    return project_id
