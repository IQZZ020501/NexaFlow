from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.teams.models import Team, TeamMembership


async def list_teams(db: AsyncSession, workspace_id: str) -> list[Team]:
    result = await db.scalars(
        select(Team)
        .where(Team.workspace_id == workspace_id)
        .order_by(Team.created_at)
    )
    return list(result.all())


async def get_team_by_id(db: AsyncSession, team_id: str) -> Team | None:
    return await db.get(Team, team_id)


async def delete_team_graph(db: AsyncSession, team_id: str) -> None:
    await db.execute(delete(TeamMembership).where(TeamMembership.team_id == team_id))
    await db.execute(delete(Team).where(Team.id == team_id))
