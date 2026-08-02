from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.identity.models import User
from nexaflow.knowledge.models import KnowledgeBase
from nexaflow.resource_permissions.models import ResourcePermission
from nexaflow.workspaces.models import WorkspaceMembership


async def list_knowledge_base_rows(
    db: AsyncSession,
    workspace_id: str,
    actor_id: str,
    workspace_role: str | None,
    resource_type: str,
):
    grant = ResourcePermission
    statement = select(KnowledgeBase, grant).outerjoin(
        grant,
        (
            (grant.workspace_id == KnowledgeBase.workspace_id)
            & (grant.resource_type == resource_type)
            & (grant.resource_id == KnowledgeBase.id)
            & (grant.user_id == actor_id)
        ),
    ).where(KnowledgeBase.workspace_id == workspace_id)

    if workspace_role != "admin":
        statement = statement.where(
            or_(
                KnowledgeBase.created_by_user_id == actor_id,
                grant.id.is_not(None),
            )
        )

    result = await db.execute(statement.order_by(KnowledgeBase.created_at))
    return result.all()


async def get_knowledge_base_by_id(
    db: AsyncSession,
    knowledge_base_id: str,
) -> KnowledgeBase | None:
    return await db.get(KnowledgeBase, knowledge_base_id)


async def get_user_grant(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    user_id: str,
    resource_type: str,
) -> ResourcePermission | None:
    return await db.scalar(
        select(ResourcePermission).where(
            ResourcePermission.workspace_id == knowledge_base.workspace_id,
            ResourcePermission.resource_type == resource_type,
            ResourcePermission.resource_id == knowledge_base.id,
            ResourcePermission.user_id == user_id,
        )
    )


async def list_resource_permission_rows(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    resource_type: str,
):
    result = await db.execute(
        select(ResourcePermission, User)
        .join(User, User.id == ResourcePermission.user_id)
        .where(
            ResourcePermission.workspace_id == knowledge_base.workspace_id,
            ResourcePermission.resource_type == resource_type,
            ResourcePermission.resource_id == knowledge_base.id,
        )
        .order_by(User.name)
    )
    return result.all()


async def get_active_workspace_member(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> User | None:
    return await db.scalar(
        select(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
            User.is_active.is_(True),
        )
    )


async def delete_knowledge_base_graph(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    resource_type: str,
) -> None:
    await db.execute(
        delete(ResourcePermission).where(
            ResourcePermission.workspace_id == knowledge_base.workspace_id,
            ResourcePermission.resource_type == resource_type,
            ResourcePermission.resource_id == knowledge_base.id,
        )
    )
    await db.execute(delete(KnowledgeBase).where(KnowledgeBase.id == knowledge_base.id))


async def delete_resource_permission(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_user_id: str,
    resource_type: str,
) -> int:
    result = await db.execute(
        delete(ResourcePermission).where(
            ResourcePermission.workspace_id == knowledge_base.workspace_id,
            ResourcePermission.resource_type == resource_type,
            ResourcePermission.resource_id == knowledge_base.id,
            ResourcePermission.user_id == target_user_id,
        )
    )
    return result.rowcount
