from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from nexaflow.core.validation import normalize_name, normalize_slug
from nexaflow.teams.models import Team
from nexaflow.teams.schemas import TeamCreateRequest, TeamResponse, TeamUpdateRequest

ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
TEAM_STATUSES = {ACTIVE_STATUS, ARCHIVED_STATUS}


def team_to_response(team: Team) -> TeamResponse:
    return TeamResponse(
        id=team.id,
        workspace_id=team.workspace_id,
        name=team.name,
        slug=team.slug,
        status=team.status,
        is_default=team.is_default,
    )


async def list_teams(db: AsyncSession, workspace_id: str) -> list[TeamResponse]:
    result = await db.scalars(
        select(Team)
        .where(Team.workspace_id == workspace_id)
        .order_by(Team.created_at)
    )
    teams = result.all()
    return [team_to_response(item) for item in teams]


async def get_team(db: AsyncSession, workspace_id: str, team_id: str) -> Team:
    team = await db.get(Team, team_id)
    if team is None or team.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    return team


async def create_team(db: AsyncSession, workspace_id: str, payload: TeamCreateRequest) -> TeamResponse:
    team = Team(
        workspace_id=workspace_id,
        name=normalize_name(payload.name),
        slug=normalize_slug(payload.slug),
        status=ACTIVE_STATUS,
    )
    db.add(team)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Team slug already exists.") from exc

    await db.refresh(team)
    return team_to_response(team)


async def update_team(db: AsyncSession, team: Team, payload: TeamUpdateRequest) -> TeamResponse:
    if payload.name is not None:
        team.name = normalize_name(payload.name)
    if payload.slug is not None:
        team.slug = normalize_slug(payload.slug)
    if payload.status is not None:
        if payload.status not in TEAM_STATUSES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid team status.")
        team.status = payload.status

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Team slug already exists.") from exc

    await db.refresh(team)
    return team_to_response(team)


async def archive_team(db: AsyncSession, team: Team) -> None:
    team.status = ARCHIVED_STATUS
    await db.commit()
