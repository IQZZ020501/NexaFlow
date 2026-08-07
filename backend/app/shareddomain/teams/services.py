from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from app.shareddomain.audit.services import record_audit_log
from app.infrastructure.validation import normalize_name
from app.infrastructure.model_utils import new_id
from app.entities.team import TEAM_MEMBER_ROLES, Team, TeamMembership
from app.entities.user import User
from app.infrastructure.repositories import team as team_repository
from app.infrastructure.repositories import workspace as workspace_repository
from app.schemas.team import (
    TeamCreateRequest,
    TeamMemberCreateRequest,
    TeamMemberResponse,
    TeamMemberUpdateRequest,
    TeamResponse,
    TeamUpdateRequest,
)
from app.schemas.user import user_to_response

ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
TEAM_STATUSES = {ACTIVE_STATUS, ARCHIVED_STATUS}


def team_to_response(team: Team) -> TeamResponse:
    return TeamResponse(
        id=team.id,
        workspace_id=team.workspace_id,
        name=team.name,
        description=team.description,
        status=team.status,
        is_default=team.is_default,
    )


async def list_teams(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[TeamResponse]:
    teams = await team_repository.list_teams(db, workspace_id, limit, offset)
    return [team_to_response(item) for item in teams]


async def get_team(db: AsyncSession, workspace_id: str, team_id: str) -> Team:
    team = await team_repository.get_team_by_id(db, team_id)
    if team is None or team.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
    return team


async def create_team(
    db: AsyncSession,
    workspace_id: str,
    payload: TeamCreateRequest,
    actor: User,
) -> TeamResponse:
    admin = await team_repository.get_active_workspace_user(
        db,
        workspace_id,
        payload.admin_user_id,
    )
    if admin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")

    team = Team(
        workspace_id=workspace_id,
        name=normalize_name(payload.name),
        description=payload.description.strip(),
        slug=new_id(),
        status=ACTIVE_STATUS,
    )
    try:
        team = await team_repository.create_team(db, team)
        await team_repository.create_team_membership(
            db,
            TeamMembership(
                workspace_id=workspace_id,
                team_id=team.id,
                user_id=admin.id,
                role="admin",
            ),
        )
        record_audit_log(
            db,
            actor,
            "team.create",
            "team",
            team.id,
            team.name,
            {
                "description": team.description,
                "workspace_id": workspace_id,
                "admin_user_id": admin.id,
            },
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Team already exists.") from exc

    team = await team_repository.refresh_team(db, team)
    return team_to_response(team)


async def update_team(
    db: AsyncSession,
    team: Team,
    payload: TeamUpdateRequest,
    actor: User,
) -> TeamResponse:
    details = payload.model_dump(exclude_none=True)
    if payload.name is not None:
        team.name = normalize_name(payload.name)
    if payload.description is not None:
        team.description = payload.description.strip()
    if payload.status is not None:
        if payload.status not in TEAM_STATUSES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid team status.")
        team.status = payload.status

    action = "team.update"
    if set(details) == {"status"} and payload.status == ARCHIVED_STATUS:
        action = "team.archive"
    elif set(details) == {"status"} and payload.status == ACTIVE_STATUS:
        action = "team.restore"
    record_audit_log(
        db,
        actor,
        action,
        "team",
        team.id,
        team.name,
        details,
        workspace_id=team.workspace_id,
    )

    try:
        team = await team_repository.save_team(db, team)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Team already exists.") from exc

    team = await team_repository.refresh_team(db, team)
    return team_to_response(team)


async def delete_team_permanently(db: AsyncSession, team: Team, actor: User) -> None:
    record_audit_log(
        db,
        actor,
        "team.delete",
        "team",
        team.id,
        team.name,
        {"description": team.description, "workspace_id": team.workspace_id},
        workspace_id=team.workspace_id,
    )
    await team_repository.delete_team_graph(db, team)
    await db.commit()


def team_member_to_response(
    membership: TeamMembership,
    user: User,
) -> TeamMemberResponse:
    return TeamMemberResponse(
        user=user_to_response(user),
        role=membership.role,
    )


def validate_team_member_role(role: str) -> None:
    if role not in TEAM_MEMBER_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid team role.")


async def actor_manages_team_admins(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
) -> bool:
    if actor.is_global_admin:
        return True
    membership = await workspace_repository.get_workspace_membership(
        db,
        workspace_id,
        actor.id,
    )
    return membership is not None and membership.role == "admin"


def require_manages_team_admins(can_manage: bool) -> None:
    if not can_manage:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Workspace admin required to manage team admins.",
        )


async def ensure_not_last_team_admin(
    db: AsyncSession,
    membership: TeamMembership,
) -> None:
    if membership.role != "admin":
        return
    if await team_repository.count_team_admins(db, membership.team_id) <= 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Team must keep at least one admin.",
        )


async def list_team_members(
    db: AsyncSession,
    team: Team,
    limit: int | None = None,
    offset: int = 0,
) -> list[TeamMemberResponse]:
    return [
        team_member_to_response(membership, user)
        for membership, user in await team_repository.list_team_member_rows(
            db,
            team,
            limit,
            offset,
        )
    ]


async def add_team_member(
    db: AsyncSession,
    team: Team,
    user_id: str,
    role: str,
    actor: User,
) -> TeamMemberResponse:
    validate_team_member_role(role)
    if role == "admin":
        require_manages_team_admins(
            await actor_manages_team_admins(db, team.workspace_id, actor),
        )
    user = await team_repository.get_active_workspace_user(
        db,
        team.workspace_id,
        user_id,
    )
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")

    membership = TeamMembership(
        workspace_id=team.workspace_id,
        team_id=team.id,
        user_id=user.id,
        role=role,
    )
    record_audit_log(
        db,
        actor,
        "team.member.add",
        "team_member",
        user.id,
        user.name,
        {"team_id": team.id, "role": role},
        workspace_id=team.workspace_id,
    )
    try:
        membership = await team_repository.create_team_membership(db, membership)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Team member already exists.",
        ) from exc

    return team_member_to_response(membership, user)


async def update_team_member_role(
    db: AsyncSession,
    team: Team,
    user_id: str,
    role: str,
    actor: User,
) -> TeamMemberResponse:
    validate_team_member_role(role)
    membership = await team_repository.get_team_membership(db, team.id, user_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team member not found.")
    if role == "admin" or membership.role == "admin":
        require_manages_team_admins(
            await actor_manages_team_admins(db, team.workspace_id, actor),
        )
    if role != "admin":
        await ensure_not_last_team_admin(db, membership)
    user = await team_repository.get_active_workspace_user(
        db,
        team.workspace_id,
        user_id,
    )
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")

    previous_role = membership.role
    membership.role = role
    record_audit_log(
        db,
        actor,
        "team.member.update",
        "team_member",
        user.id,
        user.name,
        {"team_id": team.id, "previous_role": previous_role, "role": role},
        workspace_id=team.workspace_id,
    )
    membership = await team_repository.save_team_membership(db, membership)
    await db.commit()
    return team_member_to_response(membership, user)


async def remove_team_member(
    db: AsyncSession,
    team: Team,
    user_id: str,
    actor: User,
) -> None:
    user = await team_repository.get_active_workspace_user(
        db,
        team.workspace_id,
        user_id,
    )
    membership = await team_repository.get_team_membership(db, team.id, user_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team member not found.")
    if membership.role == "admin":
        require_manages_team_admins(
            await actor_manages_team_admins(db, team.workspace_id, actor),
        )
    await ensure_not_last_team_admin(db, membership)
    await team_repository.delete_team_membership(
        db,
        team.id,
        user_id,
    )

    record_audit_log(
        db,
        actor,
        "team.member.remove",
        "team_member",
        user_id,
        user.name if user is not None else "",
        {"team_id": team.id},
        workspace_id=team.workspace_id,
    )
    await db.commit()
