from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.team import Team as TeamOrm
from app.domain.team import TeamMembership as TeamMembershipOrm
from app.domain.user import User as UserOrm
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipOrm
from app.entities.team import Team, TeamMembership
from app.entities.user import User
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


async def get_active_workspace_user(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> User | None:
    row = await db.scalar(
        select(UserOrm)
        .join(
            WorkspaceMembershipOrm,
            WorkspaceMembershipOrm.user_id == UserOrm.id,
        )
        .where(
            WorkspaceMembershipOrm.workspace_id == workspace_id,
            WorkspaceMembershipOrm.user_id == user_id,
            UserOrm.is_active.is_(True),
        )
    )
    return mapping.to_entity(User, row) if row is not None else None


async def list_team_member_rows(
    db: AsyncSession,
    team: Team,
    limit: int | None = None,
    offset: int = 0,
):
    result = await db.execute(
        select(TeamMembershipOrm, UserOrm)
        .join(UserOrm, TeamMembershipOrm.user_id == UserOrm.id)
        .where(TeamMembershipOrm.team_id == team.id)
        .order_by(UserOrm.created_at.desc(), UserOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        (
            mapping.to_entity(TeamMembership, membership),
            mapping.to_entity(User, user),
        )
        for membership, user in result.all()
    ]


async def get_team_membership(
    db: AsyncSession,
    team_id: str,
    user_id: str,
) -> TeamMembership | None:
    row = await db.scalar(
        select(TeamMembershipOrm).where(
            TeamMembershipOrm.team_id == team_id,
            TeamMembershipOrm.user_id == user_id,
        )
    )
    return mapping.to_entity(TeamMembership, row) if row is not None else None


async def create_team_membership(
    db: AsyncSession,
    entity: TeamMembership,
) -> TeamMembership:
    orm_row = await mapping.save(db, TeamMembershipOrm, entity)
    return mapping.to_entity(TeamMembership, orm_row)


async def save_team_membership(
    db: AsyncSession,
    entity: TeamMembership,
) -> TeamMembership:
    orm_row = await mapping.save(db, TeamMembershipOrm, entity)
    return mapping.to_entity(TeamMembership, orm_row)


async def delete_team_membership(
    db: AsyncSession,
    team_id: str,
    user_id: str,
) -> int:
    result = await db.execute(
        delete(TeamMembershipOrm).where(
            TeamMembershipOrm.team_id == team_id,
            TeamMembershipOrm.user_id == user_id,
        )
    )
    return result.rowcount
