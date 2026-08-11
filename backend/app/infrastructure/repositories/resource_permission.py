from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.resource_permission import ResourcePermission as ResourcePermissionORM
from app.domain.user import User as UserORM
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipORM
from app.entities.resource_permission import ResourcePermission
from app.entities.user import User
from app.infrastructure.repositories.mapping import save, to_entity


async def get_user_grant(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    user_id: str,
) -> ResourcePermission | None:
    row = await db.scalar(
        select(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == resource_id,
            ResourcePermissionORM.user_id == user_id,
        )
    )
    return to_entity(ResourcePermission, row) if row else None


async def create_resource_permission(
    db: AsyncSession,
    entity: ResourcePermission,
) -> ResourcePermission:
    row = await save(db, ResourcePermissionORM, entity)
    return to_entity(ResourcePermission, row)


async def save_resource_permission(
    db: AsyncSession,
    entity: ResourcePermission,
) -> None:
    await save(db, ResourcePermissionORM, entity)


async def list_resource_permission_rows(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[tuple[ResourcePermission, User]]:
    result = await db.execute(
        select(ResourcePermissionORM, UserORM)
        .join(UserORM, UserORM.id == ResourcePermissionORM.user_id)
        .where(
            ResourcePermissionORM.workspace_id == workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == resource_id,
        )
        .order_by(UserORM.name, UserORM.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        (
            to_entity(ResourcePermission, permission),
            to_entity(User, user),
        )
        for permission, user in result.all()
    ]


async def get_active_workspace_member(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> User | None:
    row = await db.scalar(
        select(UserORM)
        .join(
            WorkspaceMembershipORM,
            WorkspaceMembershipORM.user_id == UserORM.id,
        )
        .where(
            WorkspaceMembershipORM.workspace_id == workspace_id,
            WorkspaceMembershipORM.user_id == user_id,
            UserORM.is_active.is_(True),
        )
    )
    return to_entity(User, row) if row else None


async def delete_resource_permission(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    user_id: str,
) -> int:
    result = await db.execute(
        delete(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == resource_id,
            ResourcePermissionORM.user_id == user_id,
        )
    )
    return result.rowcount


async def delete_resource_permissions(
    db: AsyncSession,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
) -> None:
    await db.execute(
        delete(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == resource_id,
        )
    )
