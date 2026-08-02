from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.identity.models import User
from nexaflow.teams.models import Team, TeamMembership
from nexaflow.workspaces.models import Workspace, WorkspaceMembership


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.scalars(select(User).order_by(User.created_at))
    return list(result.all())


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    return await db.get(User, user_id)


async def get_active_user_by_username(db: AsyncSession, username: str) -> User | None:
    return await db.scalar(
        select(User).where(
            User.username == username,
            User.is_active.is_(True),
        )
    )


async def list_workspace_scope_rows(
    db: AsyncSession,
    user_ids: list[str],
):
    if not user_ids:
        return []

    result = await db.execute(
        select(WorkspaceMembership, Workspace)
        .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id.in_(user_ids))
        .order_by(Workspace.created_at)
    )
    return result.all()


async def list_team_scope_rows(
    db: AsyncSession,
    user_ids: list[str],
):
    if not user_ids:
        return []

    result = await db.execute(
        select(TeamMembership, Team)
        .join(Team, TeamMembership.team_id == Team.id)
        .where(TeamMembership.user_id.in_(user_ids))
        .order_by(Team.created_at)
    )
    return result.all()


async def list_admin_workspace_ids_for_user(
    db: AsyncSession,
    user_id: str,
) -> list[str]:
    result = await db.scalars(
        select(WorkspaceMembership.workspace_id).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.role == "admin",
        )
    )
    return list(result.all())


async def active_admin_counts_by_workspace(
    db: AsyncSession,
    workspace_ids: list[str],
) -> dict[str, int]:
    result = await db.execute(
        select(WorkspaceMembership.workspace_id, func.count())
        .join(User, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id.in_(workspace_ids),
            WorkspaceMembership.role == "admin",
            User.is_active.is_(True),
        )
        .group_by(WorkspaceMembership.workspace_id)
    )
    return dict(result.all())


async def list_workspace_memberships_for_user(
    db: AsyncSession,
    user_id: str,
) -> list[WorkspaceMembership]:
    result = await db.scalars(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
    )
    return list(result.all())


async def find_users_by_identity(
    db: AsyncSession,
    username: str,
    email: str,
) -> list[User]:
    result = await db.scalars(
        select(User).where(or_(User.username == username, User.email == email))
    )
    return list(result.all())


async def delete_user_graph(db: AsyncSession, user_id: str) -> None:
    await db.execute(delete(TeamMembership).where(TeamMembership.user_id == user_id))
    await db.execute(delete(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))
