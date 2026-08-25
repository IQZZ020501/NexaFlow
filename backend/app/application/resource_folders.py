from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.resource_folders import ResourceFolder
from app.entities.user import User
from app.infrastructure.repositories import resource_folders as repository
from app.infrastructure.validation import normalize_name
from app.schemas.resource_folder import (
    ResourceFolderCreateRequest,
    ResourceFolderMoveRequest,
    ResourceFolderResponse,
    ResourceFolderType,
    ResourceFolderUpdateRequest,
)
from app.shareddomain.agents.permissions import require_agent_edit
from app.shareddomain.agents.services import get_agent
from app.shareddomain.knowledge.kb import get_knowledge_base
from app.shareddomain.knowledge.permissions import require_knowledge_base_permission
from app.shareddomain.tools.permissions import require_managed_tool


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


async def list_resource_folders(
    db: AsyncSession,
    workspace_id: str,
    resource_type: ResourceFolderType,
) -> list[ResourceFolderResponse]:
    return [
        _response(folder)
        for folder in await repository.list_folders(db, workspace_id, resource_type)
    ]


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


async def create_resource_folder(
    db: AsyncSession,
    workspace_id: str,
    payload: ResourceFolderCreateRequest,
    actor: User,
) -> ResourceFolderResponse:
    await _require_parent(db, workspace_id, payload.resource_type, payload.parent_id)
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
) -> ResourceFolderResponse:
    folder = await repository.get_folder(db, workspace_id, folder_id, lock=True)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found.")
    details = payload.model_dump(exclude_unset=True)
    if "name" in details:
        folder.name = normalize_name(payload.name or "")
    if "parent_id" in details:
        if payload.parent_id == folder.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Folder cannot contain itself.")
        await _require_parent(db, workspace_id, folder.resource_type, payload.parent_id)
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
) -> None:
    folder = await repository.get_folder(db, workspace_id, folder_id, lock=True)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found.")
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
    await _require_parent(db, workspace_id, payload.resource_type, payload.folder_id)
    if payload.resource_type == "knowledge":
        resource = await get_knowledge_base(db, workspace_id, payload.resource_id)
        await require_knowledge_base_permission(db, resource, actor, workspace_role, {"edit"})
    elif payload.resource_type == "application":
        resource = await get_agent(db, workspace_id, payload.resource_id)
        require_agent_edit(resource, actor, workspace_role)
    else:
        await require_managed_tool(
            db,
            workspace_id,
            payload.resource_id,
            actor,
            workspace_role,
            lock=True,
        )
    await repository.set_resource_folder(
        db,
        workspace_id,
        payload.resource_type,
        payload.resource_id,
        payload.folder_id,
    )
    await db.commit()
