from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.team import Team, TeamMembership


async def list_teams(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[Team]:
    result = await db.scalars(
        select(Team)
        .where(Team.workspace_id == workspace_id)
        .order_by(Team.created_at.desc(), Team.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())


async def get_team_by_id(db: AsyncSession, team_id: str) -> Team | None:
    return await db.get(Team, team_id)


async def delete_team_graph(db: AsyncSession, team_id: str) -> None:
    await db.execute(delete(TeamMembership).where(TeamMembership.team_id == team_id))
    await db.execute(delete(Team).where(Team.id == team_id))
