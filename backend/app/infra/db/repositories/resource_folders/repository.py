from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.registered import RegisteredModel
from app.entities.resource_folders.models import ResourceFolder
from app.infra.db.mapping import save, to_entity
from app.domain.agents.access.permissions import AGENT_RESOURCE_TYPE
from app.domain.agents.models import Agent
from app.domain.knowledge.bases.permissions import RESOURCE_TYPE as KNOWLEDGE_RESOURCE_TYPE
from app.domain.knowledge.models import KnowledgeBase
from app.domain.platform.models import ResourcePermission as ResourcePermissionOrm
from app.domain.resource_folders.models import ResourceFolder as ResourceFolderOrm
from app.domain.tools.access.permissions import TOOL_RESOURCE_TYPE
from app.domain.tools.models import Tool

_RESOURCE_MODELS = {
    "knowledge": KnowledgeBase,
    "application": Agent,
    "model": RegisteredModel,
    "tool": Tool,
}

# Grant-scoped folder types only; models are visible workspace-wide and never
# carry resource permissions.
_GRANT_RESOURCE_TYPES = {
    "knowledge": KNOWLEDGE_RESOURCE_TYPE,
    "application": AGENT_RESOURCE_TYPE,
    "tool": TOOL_RESOURCE_TYPE,
}


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


async def list_visible_resource_folder_ids(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    viewer_id: str,
) -> set[str]:
    """Folders holding a resource the viewer owns or was granted.

    Mirrors resource authorship and explicit grants, plus builtin tools that
    every member may use. Models carry no grants, so only their owner matches.
    """
    model = _RESOURCE_MODELS[resource_type]
    grant = ResourcePermissionOrm
    statement = select(model.folder_id).where(
        model.workspace_id == workspace_id,
        model.folder_id.is_not(None),
    )
    grant_type = _GRANT_RESOURCE_TYPES.get(resource_type)
    if grant_type is None:
        # Models carry no grants, so only their owner matches.
        visible = [model.created_by_user_id == viewer_id]
    else:
        statement = statement.outerjoin(
            grant,
            and_(
                grant.workspace_id == model.workspace_id,
                grant.resource_type == grant_type,
                grant.resource_id == model.id,
                grant.user_id == viewer_id,
            ),
        )
        visible = [model.created_by_user_id == viewer_id, grant.id.is_not(None)]
        if resource_type == "tool":
            visible.append(
                or_(
                    model.kind == "builtin",
                    and_(
                        model.kind == "python",
                        model.created_by_user_id.is_(None),
                    ),
                )
            )
            statement = statement.where(model.status != "archived")
    statement = statement.where(or_(*visible))
    return {folder_id for folder_id in await db.scalars(statement) if folder_id}


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
    model = _RESOURCE_MODELS[resource_type]
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
    model = _RESOURCE_MODELS[resource_type]
    await db.execute(
        update(model)
        .where(model.workspace_id == workspace_id, model.id.in_(resource_ids))
        .values(folder_id=folder_id)
    )
