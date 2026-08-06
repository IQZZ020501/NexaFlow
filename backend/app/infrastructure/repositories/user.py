from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.team import Team as TeamOrm
from app.domain.team import TeamMembership as TeamMembershipOrm
from app.domain.user import RefreshSession as RefreshSessionOrm
from app.domain.user import User as UserOrm
from app.domain.workspace import Workspace as WorkspaceOrm
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipOrm
from app.entities.team import Team, TeamMembership
from app.entities.user import RefreshSession, User
from app.entities.workspace import WORKSPACE_ADMIN_ROLE
from app.entities.workspace import Workspace, WorkspaceMembership
from app.infrastructure.repositories import mapping


async def list_users(
    db: AsyncSession,
    limit: int | None = None,
    offset: int = 0,
) -> list[User]:
    result = await db.scalars(
        select(UserOrm)
        .order_by(UserOrm.created_at.desc(), UserOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [mapping.to_entity(User, row) for row in result.all()]


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    row = await db.get(UserOrm, user_id)
    return mapping.to_entity(User, row) if row is not None else None


async def get_active_user_by_username(db: AsyncSession, username: str) -> User | None:
    row = await db.scalar(
        select(UserOrm).where(
            UserOrm.username == username,
            UserOrm.is_active.is_(True),
        )
    )
    return mapping.to_entity(User, row) if row is not None else None


async def get_active_refresh_session(
    db: AsyncSession,
    token_hash: str,
    now: datetime,
) -> RefreshSession | None:
    row = await db.scalar(
        select(RefreshSessionOrm)
        .join(UserOrm, RefreshSessionOrm.user_id == UserOrm.id)
        .where(
            RefreshSessionOrm.token_hash == token_hash,
            RefreshSessionOrm.expires_at > now,
            UserOrm.is_active.is_(True),
        )
    )
    return mapping.to_entity(RefreshSession, row) if row is not None else None


async def delete_expired_refresh_sessions(db: AsyncSession, now: datetime) -> None:
    await db.execute(
        delete(RefreshSessionOrm).where(RefreshSessionOrm.expires_at <= now)
    )


async def delete_refresh_session(db: AsyncSession, token_hash: str) -> None:
    await db.execute(
        delete(RefreshSessionOrm).where(RefreshSessionOrm.token_hash == token_hash)
    )


async def delete_refresh_sessions_for_user(db: AsyncSession, user_id: str) -> None:
    await db.execute(
        delete(RefreshSessionOrm).where(RefreshSessionOrm.user_id == user_id)
    )


async def list_workspace_scope_rows(
    db: AsyncSession,
    user_ids: list[str],
):
    if not user_ids:
        return []

    result = await db.execute(
        select(WorkspaceMembershipOrm, WorkspaceOrm)
        .join(WorkspaceOrm, WorkspaceMembershipOrm.workspace_id == WorkspaceOrm.id)
        .where(WorkspaceMembershipOrm.user_id.in_(user_ids))
        .order_by(WorkspaceOrm.created_at)
    )
    return [
        (
            mapping.to_entity(WorkspaceMembership, membership),
            mapping.to_entity(Workspace, workspace),
        )
        for membership, workspace in result.all()
    ]


async def list_team_scope_rows(
    db: AsyncSession,
    user_ids: list[str],
):
    if not user_ids:
        return []

    result = await db.execute(
        select(TeamMembershipOrm, TeamOrm)
        .join(TeamOrm, TeamMembershipOrm.team_id == TeamOrm.id)
        .where(TeamMembershipOrm.user_id.in_(user_ids))
        .order_by(TeamOrm.created_at)
    )
    return [
        (
            mapping.to_entity(TeamMembership, membership),
            mapping.to_entity(Team, team),
        )
        for membership, team in result.all()
    ]


async def list_admin_workspace_ids_for_user(
    db: AsyncSession,
    user_id: str,
) -> list[str]:
    result = await db.scalars(
        select(WorkspaceMembershipOrm.workspace_id).where(
            WorkspaceMembershipOrm.user_id == user_id,
            WorkspaceMembershipOrm.role == WORKSPACE_ADMIN_ROLE,
        )
    )
    return list(result.all())


async def active_admin_counts_by_workspace(
    db: AsyncSession,
    workspace_ids: list[str],
) -> dict[str, int]:
    result = await db.execute(
        select(WorkspaceMembershipOrm.workspace_id, func.count())
        .join(UserOrm, WorkspaceMembershipOrm.user_id == UserOrm.id)
        .where(
            WorkspaceMembershipOrm.workspace_id.in_(workspace_ids),
            WorkspaceMembershipOrm.role == WORKSPACE_ADMIN_ROLE,
            UserOrm.is_active.is_(True),
        )
        .group_by(WorkspaceMembershipOrm.workspace_id)
    )
    return dict(result.all())


async def list_workspace_memberships_for_user(
    db: AsyncSession,
    user_id: str,
) -> list[WorkspaceMembership]:
    result = await db.scalars(
        select(WorkspaceMembershipOrm).where(
            WorkspaceMembershipOrm.user_id == user_id
        )
    )
    return [
        mapping.to_entity(WorkspaceMembership, row) for row in result.all()
    ]


async def find_users_by_identity(
    db: AsyncSession,
    username: str,
    email: str,
) -> list[User]:
    result = await db.scalars(
        select(UserOrm).where(
            or_(UserOrm.username == username, UserOrm.email == email)
        )
    )
    return [mapping.to_entity(User, row) for row in result.all()]


async def delete_user_graph(db: AsyncSession, user_id: str) -> None:
    await delete_refresh_sessions_for_user(db, user_id)
    await db.execute(delete(TeamMembershipOrm).where(TeamMembershipOrm.user_id == user_id))
    await db.execute(
        delete(WorkspaceMembershipOrm).where(WorkspaceMembershipOrm.user_id == user_id)
    )
    await db.execute(delete(UserOrm).where(UserOrm.id == user_id))


async def create_user(db: AsyncSession, entity: User) -> User:
    orm_row = await mapping.save(db, UserOrm, entity)
    return mapping.to_entity(User, orm_row)


async def create_refresh_session(
    db: AsyncSession,
    entity: RefreshSession,
) -> RefreshSession:
    orm_row = await mapping.save(db, RefreshSessionOrm, entity)
    return mapping.to_entity(RefreshSession, orm_row)


async def create_workspace_membership(
    db: AsyncSession,
    entity: WorkspaceMembership,
) -> WorkspaceMembership:
    orm_row = await mapping.save(db, WorkspaceMembershipOrm, entity)
    return mapping.to_entity(WorkspaceMembership, orm_row)


async def create_team_membership(
    db: AsyncSession,
    entity: TeamMembership,
) -> TeamMembership:
    orm_row = await mapping.save(db, TeamMembershipOrm, entity)
    return mapping.to_entity(TeamMembership, orm_row)


async def save_user(db: AsyncSession, entity: User) -> User:
    orm_row = await mapping.save(db, UserOrm, entity)
    return mapping.to_entity(User, orm_row)


async def refresh_user(db: AsyncSession, entity: User) -> User:
    return await mapping.refresh_entity(db, UserOrm, User, entity)
