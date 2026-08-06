from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.team import Team as TeamOrm
from app.domain.team import TeamMembership as TeamMembershipOrm
from app.entities.team import Team
from app.infrastructure.repositories import mapping


async def list_teams(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[Team]:
    result = await db.scalars(
        select(TeamOrm)
        .where(TeamOrm.workspace_id == workspace_id)
        .order_by(TeamOrm.created_at.desc(), TeamOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [mapping.to_entity(Team, row) for row in result.all()]


async def get_team_by_id(db: AsyncSession, team_id: str) -> Team | None:
    row = await db.get(TeamOrm, team_id)
    return mapping.to_entity(Team, row) if row is not None else None


async def create_team(db: AsyncSession, team: Team) -> Team:
    orm_row = await mapping.save(db, TeamOrm, team)
    return mapping.to_entity(Team, orm_row)


async def save_team(db: AsyncSession, team: Team) -> Team:
    orm_row = await mapping.save(db, TeamOrm, team)
    return mapping.to_entity(Team, orm_row)


async def refresh_team(db: AsyncSession, team: Team) -> Team:
    return await mapping.refresh_entity(db, TeamOrm, Team, team)


async def delete_team_graph(db: AsyncSession, team: Team) -> None:
    await db.execute(
        delete(TeamMembershipOrm).where(TeamMembershipOrm.team_id == team.id)
    )
    row = await db.get(TeamOrm, team.id)
    if row is not None:
        await db.delete(row)
