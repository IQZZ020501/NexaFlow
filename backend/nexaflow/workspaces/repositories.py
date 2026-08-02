from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.identity.models import User
from nexaflow.teams.models import Team, TeamMembership
from nexaflow.workspaces.models import Workspace, WorkspaceMembership


async def count_workspace_admins(db: AsyncSession, workspace_id: str) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == "admin",
        )
    ) or 0


async def list_all_workspaces(db: AsyncSession) -> list[Workspace]:
    result = await db.scalars(select(Workspace).order_by(Workspace.created_at))
    return list(result.all())


async def list_workspaces_for_user(db: AsyncSession, user_id: str) -> list[Workspace]:
    result = await db.scalars(
        select(Workspace)
        .join(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user_id)
        .order_by(Workspace.created_at)
    )
    return list(result.all())


async def get_workspace_by_id(db: AsyncSession, workspace_id: str) -> Workspace | None:
    return await db.get(Workspace, workspace_id)


async def get_workspace_membership(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> WorkspaceMembership | None:
    return await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )


async def list_workspace_member_rows(db: AsyncSession, workspace_id: str):
    result = await db.execute(
        select(WorkspaceMembership, User)
        .join(User, WorkspaceMembership.user_id == User.id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(User.created_at)
    )
    return result.all()


async def get_workspace_member_row(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
):
    result = await db.execute(
        select(WorkspaceMembership, User)
        .join(User, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    return result.one_or_none()


async def delete_workspace_member_graph(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> None:
    await db.execute(
        delete(TeamMembership).where(
            TeamMembership.workspace_id == workspace_id,
            TeamMembership.user_id == user_id,
        )
    )
    await db.execute(
        delete(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )


async def delete_workspace_graph(db: AsyncSession, workspace_id: str) -> None:
    team_ids = select(Team.id).where(Team.workspace_id == workspace_id)
    await db.execute(delete(TeamMembership).where(TeamMembership.team_id.in_(team_ids)))
    await db.execute(
        delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
    )
    await db.execute(delete(Team).where(Team.workspace_id == workspace_id))
    await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
