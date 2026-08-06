from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.team import Team as TeamOrm
from app.domain.team import TeamMembership as TeamMembershipOrm
from app.domain.user import User as UserOrm
from app.domain.workspace import Workspace as WorkspaceOrm
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipOrm
from app.entities.user import User
from app.entities.workspace import WORKSPACE_ADMIN_ROLE, Workspace, WorkspaceMembership
from app.infrastructure.repositories import mapping


async def count_workspace_admins(db: AsyncSession, workspace_id: str) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(WorkspaceMembershipOrm)
        .where(
            WorkspaceMembershipOrm.workspace_id == workspace_id,
            WorkspaceMembershipOrm.role == WORKSPACE_ADMIN_ROLE,
        )
    ) or 0


async def list_all_workspaces(
    db: AsyncSession,
    limit: int | None = None,
    offset: int = 0,
) -> list[Workspace]:
    result = await db.scalars(
        select(WorkspaceOrm)
        .order_by(WorkspaceOrm.created_at.desc(), WorkspaceOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [mapping.to_entity(Workspace, row) for row in result.all()]


async def list_workspaces_for_user(
    db: AsyncSession,
    user_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[Workspace]:
    result = await db.scalars(
        select(WorkspaceOrm)
        .join(WorkspaceMembershipOrm)
        .where(WorkspaceMembershipOrm.user_id == user_id)
        .order_by(WorkspaceOrm.created_at.desc(), WorkspaceOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [mapping.to_entity(Workspace, row) for row in result.all()]


async def get_workspace_by_id(db: AsyncSession, workspace_id: str) -> Workspace | None:
    row = await db.get(WorkspaceOrm, workspace_id)
    return mapping.to_entity(Workspace, row) if row is not None else None


async def get_workspace_membership(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> WorkspaceMembership | None:
    row = await db.scalar(
        select(WorkspaceMembershipOrm).where(
            WorkspaceMembershipOrm.workspace_id == workspace_id,
            WorkspaceMembershipOrm.user_id == user_id,
        )
    )
    return (
        mapping.to_entity(WorkspaceMembership, row)
        if row is not None
        else None
    )


async def list_workspace_member_rows(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
):
    result = await db.execute(
        select(WorkspaceMembershipOrm, UserOrm)
        .join(UserOrm, WorkspaceMembershipOrm.user_id == UserOrm.id)
        .where(WorkspaceMembershipOrm.workspace_id == workspace_id)
        .order_by(UserOrm.created_at.desc(), UserOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        (
            mapping.to_entity(WorkspaceMembership, membership),
            mapping.to_entity(User, user),
        )
        for membership, user in result.all()
    ]


async def get_workspace_member_row(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
):
    result = await db.execute(
        select(WorkspaceMembershipOrm, UserOrm)
        .join(UserOrm, WorkspaceMembershipOrm.user_id == UserOrm.id)
        .where(
            WorkspaceMembershipOrm.workspace_id == workspace_id,
            WorkspaceMembershipOrm.user_id == user_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        return None
    membership, user = row
    return (
        mapping.to_entity(WorkspaceMembership, membership),
        mapping.to_entity(User, user),
    )


async def delete_workspace_member_graph(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> None:
    await db.execute(
        delete(TeamMembershipOrm).where(
            TeamMembershipOrm.workspace_id == workspace_id,
            TeamMembershipOrm.user_id == user_id,
        )
    )
    await db.execute(
        delete(WorkspaceMembershipOrm).where(
            WorkspaceMembershipOrm.workspace_id == workspace_id,
            WorkspaceMembershipOrm.user_id == user_id,
        )
    )


async def delete_workspace_graph(db: AsyncSession, workspace_id: str) -> None:
    team_ids = select(TeamOrm.id).where(TeamOrm.workspace_id == workspace_id)
    await db.execute(
        delete(TeamMembershipOrm).where(TeamMembershipOrm.team_id.in_(team_ids))
    )
    await db.execute(
        delete(WorkspaceMembershipOrm).where(
            WorkspaceMembershipOrm.workspace_id == workspace_id
        )
    )
    await db.execute(delete(TeamOrm).where(TeamOrm.workspace_id == workspace_id))
    await db.execute(delete(WorkspaceOrm).where(WorkspaceOrm.id == workspace_id))


async def create_workspace(db: AsyncSession, entity: Workspace) -> Workspace:
    orm_row = await mapping.save(db, WorkspaceOrm, entity)
    return mapping.to_entity(Workspace, orm_row)


async def create_workspace_membership(
    db: AsyncSession,
    entity: WorkspaceMembership,
) -> WorkspaceMembership:
    orm_row = await mapping.save(db, WorkspaceMembershipOrm, entity)
    return mapping.to_entity(WorkspaceMembership, orm_row)


async def save_workspace(db: AsyncSession, entity: Workspace) -> Workspace:
    orm_row = await mapping.save(db, WorkspaceOrm, entity)
    return mapping.to_entity(Workspace, orm_row)


async def save_workspace_membership(
    db: AsyncSession,
    entity: WorkspaceMembership,
) -> WorkspaceMembership:
    orm_row = await mapping.save(db, WorkspaceMembershipOrm, entity)
    return mapping.to_entity(WorkspaceMembership, orm_row)


async def refresh_workspace(db: AsyncSession, entity: Workspace) -> Workspace:
    return await mapping.refresh_entity(db, WorkspaceOrm, Workspace, entity)


async def refresh_workspace_membership(
    db: AsyncSession,
    entity: WorkspaceMembership,
) -> WorkspaceMembership:
    return await mapping.refresh_entity(
        db,
        WorkspaceMembershipOrm,
        WorkspaceMembership,
        entity,
    )
