"""Personal project context for public Agent conversations.

Business projects own a separate source tree. Conversation work trees and Run
snapshots retain their existing lifetime and isolation rules.
"""

import asyncio
import hashlib

from fastapi import HTTPException

from app.application.artifacts.service import get_authorized_artifact
from app.application.projects.service import (
    project_run_snapshot,
    require_project,
    save_changes,
)
from app.application.publications.service import get_workspace_published_agent_context
from app.domain.artifacts.services import (
    ARTIFACT_MEDIA_TYPES,
    artifact_format_from_filename,
)
from app.domain.projects.imports import import_file_tree
from app.domain.projects.services import ProjectFileConflict
from app.entities.artifacts import GeneratedArtifact
from app.entities.defaults import utc_now
from app.entities.projects import AgentProject, ChatConversation, ChatProject
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.projects import chat as repository
from app.infra.db.repositories.projects import repository as files
from app.schemas.projects import ChatProjectFileResponse, ChatProjectResponse


def project_response(project):
    return ChatProjectResponse(
        **{key: getattr(project, key) for key in ChatProjectResponse.model_fields}
    )


async def _scope(db, agent_id, actor, *, write=False):
    context = await get_workspace_published_agent_context(db, agent_id, actor)
    if write:
        if await runs.lock_agent(db, agent_id) is None:
            raise HTTPException(404, "Published agent not found.")
    return context.agent.workspace_id


async def _project(db, workspace_id, agent_id, owner_id, project_id, *, editable=False):
    project = await repository.get_project(db, project_id)
    if (
        project is None
        or project.workspace_id != workspace_id
        or project.agent_id != agent_id
        or project.owner_user_id != owner_id
        or project.dissolved_at is not None
    ):
        raise HTTPException(404, "Chat project not found.")
    if editable and project.archived:
        raise HTTPException(409, "Chat project is archived.")
    return project


async def list_projects(db, agent_id, actor):
    workspace_id = await _scope(db, agent_id, actor)
    return [
        project_response(item)
        for item in await repository.list_projects(db, workspace_id, agent_id, actor.id)
    ]


async def create_project(db, agent_id, actor, payload):
    workspace_id = await _scope(db, agent_id, actor, write=True)
    tree = await files.save_project(
        db,
        AgentProject(
            workspace_id=workspace_id,
            created_by_user_id=actor.id,
            name=payload.name,
        ),
    )
    project = await repository.save_project(
        db,
        ChatProject(
            workspace_id=workspace_id,
            agent_id=agent_id,
            owner_user_id=actor.id,
            file_tree_id=tree.id,
            name=payload.name,
            instructions=payload.instructions,
        ),
    )
    await db.commit()
    return project_response(project)


async def update_project(db, agent_id, actor, project_id, payload):
    workspace_id = await _scope(db, agent_id, actor, write=True)
    project = await _project(db, workspace_id, agent_id, actor.id, project_id)
    if project.archived and payload.archived:
        raise HTTPException(409, "Chat project is archived.")
    project.name, project.instructions, project.archived = (
        payload.name,
        payload.instructions,
        payload.archived,
    )
    project.updated_at = utc_now()
    await repository.save_project(db, project)
    await db.commit()
    return project_response(project)


async def _require_idle(db, agent_id, owner_id, conversation_id):
    if await runs.get_active_agent_run(
        db, agent_id, "public", owner_id, conversation_id
    ):
        raise HTTPException(409, "Cannot move a conversation while it is running.")


async def dissolve_project(db, agent_id, actor, project_id):
    workspace_id = await _scope(db, agent_id, actor, write=True)
    project = await _project(db, workspace_id, agent_id, actor.id, project_id)
    for item in await repository.list_conversations(
        db, workspace_id, agent_id, actor.id
    ):
        if item.project_id == project.id:
            await _require_idle(db, agent_id, actor.id, item.conversation_id)
    await repository.detach_project(db, project.id)
    # Keep immutable sources referenced by historical Run snapshots.
    project.dissolved_at = project.updated_at = utc_now()
    await repository.save_project(db, project)
    await db.commit()


async def create_conversation(db, agent_id, actor, project_id):
    workspace_id = await _scope(db, agent_id, actor, write=True)
    await _project(db, workspace_id, agent_id, actor.id, project_id, editable=True)
    conversation = await repository.save_conversation(
        db,
        ChatConversation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            owner_user_id=actor.id,
            project_id=project_id,
        ),
    )
    await db.commit()
    return conversation


async def move_conversation(db, agent_id, actor, conversation_id, project_id):
    workspace_id = await _scope(db, agent_id, actor, write=True)
    conversation = await repository.get_conversation(
        db, agent_id, actor.id, conversation_id
    )
    if conversation is None:
        previous = await runs.list_agent_runs(
            db, agent_id, "public", actor.id, limit=1, conversation_id=conversation_id
        )
        if not previous:
            raise HTTPException(404, "Conversation not found.")
        conversation = ChatConversation(
            workspace_id=workspace_id,
            agent_id=agent_id,
            owner_user_id=actor.id,
            conversation_id=conversation_id,
        )
    await _require_idle(db, agent_id, actor.id, conversation_id)
    if project_id is not None:
        await _project(db, workspace_id, agent_id, actor.id, project_id, editable=True)
    conversation.project_id = project_id
    await repository.save_conversation(db, conversation)
    await db.commit()
    return conversation


async def _source_tree(db, agent_id, actor, project_id, *, editable=False):
    workspace_id = await _scope(db, agent_id, actor, write=editable)
    project = await _project(
        db, workspace_id, agent_id, actor.id, project_id, editable=editable
    )
    tree = await require_project(
        db, workspace_id, project.file_tree_id, actor.id, lock=editable
    )
    return project, tree


def file_response(item):
    return ChatProjectFileResponse(
        id=item.id,
        path=item.path,
        size_bytes=item.size_bytes,
        content_hash=item.content_hash,
    )


async def list_files(db, agent_id, actor, project_id):
    _, tree = await _source_tree(db, agent_id, actor, project_id)
    return [
        file_response(item)
        for item in await files.latest_files(db, tree.id)
        if not item.deleted
    ]


async def _add_files(db, project, tree, imported):
    if any(len(f"{project.id}/{path}") > 512 for path, _ in imported):
        raise HTTPException(
            422, "Chat project files exceed their limits or contain invalid paths."
        )
    heads = {item.path: item for item in await files.latest_files(db, tree.id)}
    if any(path in heads and not heads[path].deleted for path, _ in imported):
        raise HTTPException(409, "Chat project already has a file with this path.")
    try:
        await save_changes(
            db,
            tree,
            [
                {
                    "path": path,
                    "role": "source",
                    "content": content,
                    "expected_version_id": heads[path].id if path in heads else None,
                }
                for path, content in imported
            ],
        )
    except (ValueError, ProjectFileConflict) as exc:
        raise HTTPException(
            422, "Chat project files exceed their limits or contain invalid paths."
        ) from exc
    project.updated_at = utc_now()
    await repository.save_project(db, project)
    await db.commit()
    return [
        file_response(item)
        for item in await files.latest_files(db, tree.id)
        if not item.deleted
    ]


async def upload_files(db, agent_id, actor, project_id, uploads):
    project, tree = await _source_tree(db, agent_id, actor, project_id, editable=True)
    try:
        imported = [
            (item["path"], item["content"])
            for item in await asyncio.to_thread(import_file_tree, uploads)
        ]
    except ValueError as exc:
        raise HTTPException(
            422, "Chat project files exceed their limits or contain invalid paths."
        ) from exc
    return await _add_files(db, project, tree, imported)


async def save_artifact(db, agent_id, actor, project_id, artifact_id):
    project, tree = await _source_tree(db, agent_id, actor, project_id, editable=True)
    artifact = await get_authorized_artifact(db, artifact_id, actor)
    run = await runs.get_agent_run_by_id(db, artifact.run_id)
    if run.parent_run_id:
        run = await runs.get_agent_run_by_id(db, run.root_run_id)
    if (
        run.agent_id != agent_id
        or run.access_source != "public"
        or run.consumer_id != actor.id
    ):
        raise HTTPException(404, "Artifact not found.")
    return await _add_files(db, project, tree, [(artifact.filename, artifact.content)])


async def read_file(db, agent_id, actor, project_id, version_id):
    _, tree = await _source_tree(db, agent_id, actor, project_id)
    version = await files.get_version(db, tree.id, version_id)
    heads = {
        item.id for item in await files.latest_files(db, tree.id) if not item.deleted
    }
    if version is None or version.id not in heads:
        raise HTTPException(404, "Chat project file not found.")
    filename = version.path.rsplit("/", 1)[-1]
    file_format = artifact_format_from_filename(filename)
    return GeneratedArtifact(
        id=version.id,
        filename=filename,
        format=file_format,
        media_type=ARTIFACT_MEDIA_TYPES.get(file_format, "application/octet-stream"),
        content=version.content,
        content_hash=version.content_hash,
        size_bytes=version.size_bytes,
    )


async def delete_file(db, agent_id, actor, project_id, version_id):
    project, tree = await _source_tree(db, agent_id, actor, project_id, editable=True)
    current = next(
        (
            item
            for item in await files.latest_files(db, tree.id)
            if item.id == version_id and not item.deleted
        ),
        None,
    )
    if current is None:
        raise HTTPException(404, "Chat project file not found.")
    await save_changes(
        db,
        tree,
        [
            {
                "path": current.path,
                "role": "source",
                "deleted": True,
                "expected_version_id": current.id,
            }
        ],
    )
    project.updated_at = utc_now()
    await repository.save_project(db, project)
    await db.commit()


async def require_writable_conversation(db, run):
    """Serialize new public input with project moves, archival and dissolution."""
    if run.access_source != "public":
        return
    await runs.lock_agent(db, run.agent_id)
    conversation = await repository.get_conversation(
        db, run.agent_id, run.consumer_id, run.conversation_id
    )
    if conversation is None or conversation.project_id is None:
        return
    return await _project(
        db,
        run.workspace_id,
        run.agent_id,
        run.consumer_id,
        conversation.project_id,
        editable=True,
    )


async def freeze_project_context(db, run):
    """Called before persisting a public Run, under the application lock."""
    project = await require_writable_conversation(db, run)
    if project is None:
        return
    snapshot = await project_run_snapshot(
        db, run.workspace_id, project.file_tree_id, run.consumer_id
    )
    run.application_snapshot["chat_project"] = {
        "id": project.id,
        "name": project.name,
        "instructions": project.instructions,
        "workspace_id": run.workspace_id,
        "agent_id": run.agent_id,
        "owner_id": run.consumer_id,
        "source_tree": snapshot,
    }


async def frozen_source_files(db, run):
    """Frozen versions remain readable after source edits or project dissolution."""
    snapshot = run.application_snapshot.get("chat_project")
    if not snapshot:
        return {}
    if (
        run.access_source != "public"
        or snapshot.get("workspace_id") != run.workspace_id
        or snapshot.get("agent_id") != run.agent_id
        or snapshot.get("owner_id") != run.consumer_id
    ):
        raise ValueError("Chat project file scope is invalid.")
    tree = snapshot["source_tree"]
    await require_project(db, run.workspace_id, tree["id"], run.consumer_id)
    result = {}
    for item in tree["files"]:
        if item["deleted"]:
            continue
        version = await files.get_version(db, tree["id"], item["version_id"])
        if (
            version is None
            or version.path != item["path"]
            or version.role != "source"
            or hashlib.sha256(version.content).hexdigest() != item["sha256"]
        ):
            raise ValueError("Chat project file snapshot is invalid.")
        result[f"{snapshot['id']}/{version.path}"] = version.content
    return result


__all__ = [
    "create_conversation",
    "create_project",
    "delete_file",
    "dissolve_project",
    "freeze_project_context",
    "list_files",
    "list_projects",
    "move_conversation",
    "read_file",
    "require_writable_conversation",
    "save_artifact",
    "update_project",
    "upload_files",
]
