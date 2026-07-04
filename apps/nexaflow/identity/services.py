import secrets

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from nexaflow.core.config import Settings
from nexaflow.core.validation import normalize_email, normalize_name, normalize_username
from nexaflow.identity.models import User
from nexaflow.identity.schemas import (
    MembershipResponse,
    MeResponse,
    TokenResponse,
    UserCreateRequest,
    UserPasswordResetResponse,
    UserResponse,
    UserTeamResponse,
    UserUpdateRequest,
    UserWorkspaceResponse,
)
from nexaflow.identity.security import create_access_token, hash_password, verify_password
from nexaflow.teams.models import Team, TeamMembership
from nexaflow.workspaces.models import Workspace, WorkspaceMembership


def user_to_response(
    user: User,
    workspaces: list[UserWorkspaceResponse] | None = None,
    teams: list[UserTeamResponse] | None = None,
) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        name=user.name,
        is_global_admin=user.is_global_admin,
        must_change_password=user.must_change_password,
        is_active=user.is_active,
        created_at=user.created_at,
        workspaces=workspaces or [],
        teams=teams or [],
    )


async def user_workspaces_by_user_id(
    db: AsyncSession,
    users: list[User],
) -> dict[str, list[UserWorkspaceResponse]]:
    user_ids = [user.id for user in users]
    workspaces_by_user: dict[str, list[UserWorkspaceResponse]] = {
        user_id: [] for user_id in user_ids
    }
    if not user_ids:
        return workspaces_by_user

    result = await db.execute(
        select(WorkspaceMembership, Workspace)
        .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id.in_(user_ids))
        .order_by(Workspace.created_at)
    )
    for membership, workspace in result.all():
        workspaces_by_user.setdefault(membership.user_id, []).append(
            UserWorkspaceResponse(
                id=workspace.id,
                name=workspace.name,
                slug=workspace.slug,
                is_default=workspace.is_default,
                role=membership.role,
            )
        )
    return workspaces_by_user


async def user_teams_by_user_id(
    db: AsyncSession,
    users: list[User],
) -> dict[str, list[UserTeamResponse]]:
    user_ids = [user.id for user in users]
    teams_by_user: dict[str, list[UserTeamResponse]] = {
        user_id: [] for user_id in user_ids
    }
    if not user_ids:
        return teams_by_user

    result = await db.execute(
        select(TeamMembership, Team)
        .join(Team, TeamMembership.team_id == Team.id)
        .where(TeamMembership.user_id.in_(user_ids))
        .order_by(Team.created_at)
    )
    for membership, team in result.all():
        teams_by_user.setdefault(membership.user_id, []).append(
            UserTeamResponse(
                id=team.id,
                workspace_id=team.workspace_id,
                name=team.name,
                slug=team.slug,
                is_default=team.is_default,
                role=membership.role,
            )
        )
    return teams_by_user


async def user_to_response_with_scopes(db: AsyncSession, user: User) -> UserResponse:
    workspaces_by_user = await user_workspaces_by_user_id(db, [user])
    teams_by_user = await user_teams_by_user_id(db, [user])
    return user_to_response(
        user,
        workspaces_by_user.get(user.id, []),
        teams_by_user.get(user.id, []),
    )


async def list_users(db: AsyncSession) -> list[UserResponse]:
    result = await db.scalars(select(User).order_by(User.created_at))
    users = result.all()
    workspaces_by_user = await user_workspaces_by_user_id(db, users)
    teams_by_user = await user_teams_by_user_id(db, users)
    return [
        user_to_response(
            item,
            workspaces_by_user.get(item.id, []),
            teams_by_user.get(item.id, []),
        )
        for item in users
    ]


async def get_user(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return user


async def create_user(
    db: AsyncSession,
    payload: UserCreateRequest,
) -> UserPasswordResetResponse:
    team_ids = list(dict.fromkeys(payload.team_ids))
    if team_ids and not payload.workspace_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Workspace is required when assigning teams.",
        )

    workspace: Workspace | None = None
    teams: list[Team] = []
    if payload.workspace_id:
        workspace = await db.get(Workspace, payload.workspace_id)
        if workspace is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
        if workspace.status != "active":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace is not active.")

    if team_ids and workspace:
        for team_id in team_ids:
            team = await db.get(Team, team_id)
            if team is not None:
                teams.append(team)
        if len(teams) != len(team_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
        if any(team.workspace_id != workspace.id for team in teams):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Teams must belong to selected workspace.",
            )

    initial_password = secrets.token_urlsafe(18)
    user = User(
        username=normalize_username(payload.username),
        email=normalize_email(payload.email),
        name=normalize_name(payload.name),
        password_hash=hash_password(initial_password),
        is_global_admin=payload.is_global_admin,
        must_change_password=True,
    )
    db.add(user)

    try:
        await db.flush()
        if workspace:
            db.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role="member",
                )
            )
        for team in teams:
            db.add(TeamMembership(team_id=team.id, user_id=user.id, role="member"))
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Username or email already exists.",
        ) from exc

    await db.refresh(user)
    return UserPasswordResetResponse(
        user=await user_to_response_with_scopes(db, user),
        initial_password=initial_password,
    )


async def update_user(
    db: AsyncSession,
    user: User,
    actor: User,
    payload: UserUpdateRequest,
) -> UserResponse:
    if payload.username is not None:
        user.username = normalize_username(payload.username)
    if payload.email is not None:
        user.email = normalize_email(payload.email)
    if payload.name is not None:
        user.name = normalize_name(payload.name)
    if payload.is_global_admin is not None:
        if user.id == actor.id and not payload.is_global_admin:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Current user cannot remove own global admin role.",
            )
        user.is_global_admin = payload.is_global_admin
    if payload.is_active is not None:
        if user.id == actor.id and not payload.is_active:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Current user cannot be disabled.",
            )
        user.is_active = payload.is_active

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Username or email already exists.",
        ) from exc

    await db.refresh(user)
    return await user_to_response_with_scopes(db, user)


async def reset_user_password(
    db: AsyncSession,
    user: User,
) -> UserPasswordResetResponse:
    initial_password = secrets.token_urlsafe(18)
    user.password_hash = hash_password(initial_password)
    user.must_change_password = True
    await db.commit()
    await db.refresh(user)
    return UserPasswordResetResponse(
        user=await user_to_response_with_scopes(db, user),
        initial_password=initial_password,
    )


async def deactivate_user(db: AsyncSession, user: User, actor: User) -> None:
    if user.id == actor.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Current user cannot be deleted.",
        )
    user.is_active = False
    await db.commit()


async def authenticate_user(
    db: AsyncSession,
    username_or_email: str,
    password: str,
    settings: Settings,
) -> TokenResponse:
    identifier = username_or_email.strip()
    normalized_email = identifier.lower()
    user = await db.scalar(
        select(User).where(
            or_(User.username == identifier, User.email == normalized_email),
            User.is_active.is_(True),
        )
    )
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials.")

    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        must_change_password=user.must_change_password,
    )


async def change_password(db: AsyncSession, user: User, new_password: str) -> None:
    if not user.must_change_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password change is not required.")
    if verify_password(new_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must be different.")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await db.commit()


async def get_me(db: AsyncSession, user: User) -> MeResponse:
    memberships = await db.scalars(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id)
    )
    membership_list = memberships.all()
    return MeResponse(
        user=user_to_response(user),
        memberships=[
            MembershipResponse(workspace_id=item.workspace_id, role=item.role)
            for item in membership_list
        ],
    )


async def find_user_by_identity(db: AsyncSession, username: str, email: str) -> User | None:
    username = normalize_username(username)
    email = normalize_email(email)
    users_result = await db.scalars(
        select(User).where(or_(User.username == username, User.email == email))
    )
    users = users_result.all()
    if not users:
        return None
    if len(users) == 1 and users[0].username == username and users[0].email == email:
        return users[0]
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "Username and email must identify the same user.",
    )
