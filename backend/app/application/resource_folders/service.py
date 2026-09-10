from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.resource_folders.models import ResourceFolder
from app.entities.identity.user import User
from app.infra.db.repositories.resource_folders import repository as repository
from app.infra.runtime.validation import normalize_name
from app.infra.db.repositories.models import registry as model_registry
from app.schemas.resource_folders.contracts import (
    ResourceFolderBatchMoveRequest,
    ResourceFolderCreateRequest,
    ResourceFolderMoveRequest,
    ResourceFolderResponse,
    ResourceFolderType,
    ResourceFolderUpdateRequest,
)
from app.domain.agents.access.permissions import require_agent_edit
from app.domain.agents.service import get_agent
from app.domain.knowledge.bases.service import get_knowledge_base
from app.domain.knowledge.bases.permissions import require_knowledge_base_permission
from app.domain.tools.access.permissions import require_managed_tool


def _response(folder: ResourceFolder) -> ResourceFolderResponse:
    return ResourceFolderResponse(**folder.__dict__)


def descendant_folder_ids(
    folders: list[ResourceFolder],
    folder_id: str,
) -> set[str]:
    descendants = {folder_id}
    changed = True
    while changed:
        changed = False
        for item in folders:
            if item.parent_id in descendants and item.id not in descendants:
                descendants.add(item.id)
                changed = True
    return descendants


def ancestor_folder_ids(
    folders: list[ResourceFolder],
    folder_ids: set[str],
) -> set[str]:
    """The given folder ids plus every ancestor folder."""
    parents = {folder.id: folder.parent_id for folder in folders}
    result = set(folder_ids)
    pending = list(folder_ids)
    while pending:
        parent_id = parents.get(pending.pop())
        if parent_id is not None and parent_id not in result:
            result.add(parent_id)
            pending.append(parent_id)
    return result


async def _visible_folder_ids(
    db: AsyncSession,
    workspace_id: str,
    resource_type: ResourceFolderType,
    folders: list[ResourceFolder],
    viewer: User,
) -> set[str]:
    """Own folders plus folders reached through the viewer's own or granted resources."""
    visible = await repository.list_visible_resource_folder_ids(
        db,
        workspace_id,
        resource_type,
        viewer.id,
    )
    visible.update(
        folder.id for folder in folders if folder.created_by_user_id == viewer.id
    )
    return ancestor_folder_ids(folders, visible)


async def list_resource_folders(
    db: AsyncSession,
    workspace_id: str,
    resource_type: ResourceFolderType,
    viewer: User,
) -> list[ResourceFolderResponse]:
    folders = await repository.list_folders(db, workspace_id, resource_type)
    visible = await _visible_folder_ids(
        db,
        workspace_id,
        resource_type,
        folders,
        viewer,
    )
    return [_response(folder) for folder in folders if folder.id in visible]


async def _require_parent(
    db: AsyncSession,
    workspace_id: str,
    resource_type: ResourceFolderType,
    parent_id: str | None,
) -> ResourceFolder | None:
    if parent_id is None:
        return None
    parent = await repository.get_folder(db, workspace_id, parent_id)
    if parent is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Folder parent not found.")
    if parent.resource_type != resource_type:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Folder type does not match.")
    return parent


def can_manage_folder(folder: ResourceFolder, actor: User) -> bool:
    """Only the creator owns the folder tree; global admins keep an escape hatch."""
    return folder.created_by_user_id == actor.id or actor.is_global_admin


def require_manage_folder(folder: ResourceFolder, actor: User) -> None:
    if can_manage_folder(folder, actor):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Folder owner required.",
    )


async def _require_visible_parent(
    db: AsyncSession,
    workspace_id: str,
    resource_type: ResourceFolderType,
    parent: ResourceFolder | None,
    actor: User,
) -> None:
    """Nesting is limited to folders the actor can already see."""
    if parent is None:
        return
    folders = await repository.list_folders(db, workspace_id, resource_type)
    visible = await _visible_folder_ids(
        db,
        workspace_id,
        resource_type,
        folders,
        actor,
    )
    if parent.id not in visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found.")


async def create_resource_folder(
    db: AsyncSession,
    workspace_id: str,
    payload: ResourceFolderCreateRequest,
    actor: User,
) -> ResourceFolderResponse:
    parent = await _require_parent(
        db,
        workspace_id,
        payload.resource_type,
        payload.parent_id,
    )
    await _require_visible_parent(
        db,
        workspace_id,
        payload.resource_type,
        parent,
        actor,
    )
    folder = ResourceFolder(
        workspace_id=workspace_id,
        resource_type=payload.resource_type,
        parent_id=payload.parent_id,
        name=normalize_name(payload.name),
        created_by_user_id=actor.id,
    )
    try:
        folder = await repository.create_folder(db, folder)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Folder name already exists.") from exc
    return _response(folder)


async def update_resource_folder(
    db: AsyncSession,
    workspace_id: str,
    folder_id: str,
    payload: ResourceFolderUpdateRequest,
    actor: User,
) -> ResourceFolderResponse:
    folder = await repository.get_folder(db, workspace_id, folder_id, lock=True)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found.")
    require_manage_folder(folder, actor)
    details = payload.model_dump(exclude_unset=True)
    if "name" in details:
        folder.name = normalize_name(payload.name or "")
    if "parent_id" in details:
        if payload.parent_id == folder.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Folder cannot contain itself.")
        parent = await _require_parent(
            db,
            workspace_id,
            folder.resource_type,
            payload.parent_id,
        )
        await _require_visible_parent(
            db,
            workspace_id,
            folder.resource_type,
            parent,
            actor,
        )
        descendants = descendant_folder_ids(
            await repository.list_folders(db, workspace_id, folder.resource_type),
            folder.id,
        )
        if payload.parent_id in descendants:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Folder cycle is not allowed.")
        folder.parent_id = payload.parent_id
    try:
        folder = await repository.save_folder(db, folder)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Folder name already exists.") from exc
    return _response(folder)


async def delete_resource_folder(
    db: AsyncSession,
    workspace_id: str,
    folder_id: str,
    actor: User,
) -> None:
    folder = await repository.get_folder(db, workspace_id, folder_id, lock=True)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found.")
    require_manage_folder(folder, actor)
    try:
        await repository.delete_folder(
            db,
            workspace_id,
            folder.id,
            folder.parent_id,
            folder.resource_type,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Folder cannot be deleted.") from exc


async def move_resource(
    db: AsyncSession,
    workspace_id: str,
    payload: ResourceFolderMoveRequest,
    actor: User,
    workspace_role: str | None,
) -> None:
    await _move_resources(
        db,
        workspace_id,
        payload.resource_type,
        [payload.resource_id],
        payload.folder_id,
        actor,
        workspace_role,
    )


async def move_resources(
    db: AsyncSession,
    workspace_id: str,
    payload: ResourceFolderBatchMoveRequest,
    actor: User,
    workspace_role: str | None,
) -> None:
    await _move_resources(
        db,
        workspace_id,
        payload.resource_type,
        payload.resource_ids,
        payload.folder_id,
        actor,
        workspace_role,
    )


async def _move_resources(
    db: AsyncSession,
    workspace_id: str,
    resource_type: ResourceFolderType,
    resource_ids: list[str],
    folder_id: str | None,
    actor: User,
    workspace_role: str | None,
) -> None:
    parent = await _require_parent(db, workspace_id, resource_type, folder_id)
    await _require_visible_parent(
        db,
        workspace_id,
        resource_type,
        parent,
        actor,
    )
    for resource_id in resource_ids:
        if resource_type == "knowledge":
            resource = await get_knowledge_base(db, workspace_id, resource_id)
            await require_knowledge_base_permission(
                db,
                resource,
                actor,
                {"edit"},
            )
        elif resource_type == "application":
            resource = await get_agent(db, workspace_id, resource_id)
            require_agent_edit(resource, actor)
        elif resource_type == "model":
            if workspace_role != "admin" and not actor.is_global_admin:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace admin required.")
            resource = await model_registry.get_registered_model_by_id(db, resource_id)
            if resource is None or resource.workspace_id != workspace_id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found.")
        else:
            await require_managed_tool(
                db,
                workspace_id,
                resource_id,
                actor,
                workspace_role,
                lock=True,
            )
    await repository.set_resources_folder(
        db,
        workspace_id,
        resource_type,
        resource_ids,
        folder_id,
    )
    await db.commit()
