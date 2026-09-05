from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.resource_folders import ResourceFolder
from app.infrastructure.repositories.mapping import save, to_entity
from app.shareddomain.agents.models import Agent
from app.shareddomain.knowledge.models import KnowledgeBase
from app.shareddomain.resource_folders.models import ResourceFolder as ResourceFolderOrm
from app.shareddomain.tools.models import Tool


async def list_folders(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
) -> list[ResourceFolder]:
    rows = await db.scalars(
        select(ResourceFolderOrm)
        .where(
            ResourceFolderOrm.workspace_id == workspace_id,
            ResourceFolderOrm.resource_type == resource_type,
        )
        .order_by(ResourceFolderOrm.name, ResourceFolderOrm.id)
    )
    return [to_entity(ResourceFolder, row) for row in rows.all()]


async def get_folder(
    db: AsyncSession,
    workspace_id: str,
    folder_id: str,
    *,
    lock: bool = False,
) -> ResourceFolder | None:
    statement = select(ResourceFolderOrm).where(
        ResourceFolderOrm.workspace_id == workspace_id,
        ResourceFolderOrm.id == folder_id,
    )
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    return to_entity(ResourceFolder, row) if row is not None else None


async def create_folder(db: AsyncSession, folder: ResourceFolder) -> ResourceFolder:
    row = await save(db, ResourceFolderOrm, folder)
    return to_entity(ResourceFolder, row)


async def save_folder(db: AsyncSession, folder: ResourceFolder) -> ResourceFolder:
    row = await save(db, ResourceFolderOrm, folder)
    return to_entity(ResourceFolder, row)


async def delete_folder(
    db: AsyncSession,
    workspace_id: str,
    folder_id: str,
    parent_id: str | None,
    resource_type: str,
) -> None:
    await db.execute(
        update(ResourceFolderOrm)
        .where(
            ResourceFolderOrm.workspace_id == workspace_id,
            ResourceFolderOrm.resource_type == resource_type,
            ResourceFolderOrm.parent_id == folder_id,
        )
        .values(parent_id=parent_id)
    )
    model = {
        "knowledge": KnowledgeBase,
        "application": Agent,
        "tool": Tool,
    }[resource_type]
    await db.execute(
        update(model)
        .where(model.workspace_id == workspace_id, model.folder_id == folder_id)
        .values(folder_id=parent_id)
    )
    await db.execute(
        delete(ResourceFolderOrm).where(
            ResourceFolderOrm.workspace_id == workspace_id,
            ResourceFolderOrm.resource_type == resource_type,
            ResourceFolderOrm.id == folder_id,
        )
    )


async def set_resources_folder(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    resource_ids: list[str],
    folder_id: str | None,
) -> None:
    model = {
        "knowledge": KnowledgeBase,
        "application": Agent,
        "tool": Tool,
    }[resource_type]
    await db.execute(
        update(model)
        .where(model.workspace_id == workspace_id, model.id.in_(resource_ids))
        .values(folder_id=folder_id)
    )
