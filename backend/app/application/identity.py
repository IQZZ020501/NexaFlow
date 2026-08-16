import logging
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from app.shareddomain.audit.services import record_audit_log
from app.infrastructure.config import Settings
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.agent_rate_limit import (
    LoginRateLimitExceeded,
    LoginRateLimitUnavailable,
    enforce_login_rate_limit,
)
from app.infrastructure.validation import normalize_email, normalize_name, normalize_username
from app.entities.user import RefreshSession, User
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import tools as tools_repository
from app.infrastructure.repositories import team as team_repository
from app.infrastructure.repositories import workspace as workspace_repository
from app.schemas.user import (
    MembershipResponse,
    MeResponse,
    TokenResponse,
    UserCreateRequest,
    UserPasswordResetResponse,
    UserResponse,
    UserTeamResponse,
    UserUpdateRequest,
    UserWorkspaceResponse,
    user_to_response,
)
from app.infrastructure.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.infrastructure.system_log import record_system_log
from app.shareddomain.workflows.uploads import queue_upload_cleanups
from app.shareddomain.tools.services import delete_owned_mcp_servers_for_user
from app.entities.team import Team, TeamMembership
from app.entities.workspace import Workspace, WorkspaceMembership

logger = get_logger(__name__)

def access_token_response(user: User, settings: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.jwt_expires_minutes * 60,
        must_change_password=user.must_change_password,
    )


async def issue_refresh_session(
    db: AsyncSession,
    user: User,
    settings: Settings,
) -> str:
    now = utc_now()
    await user_repository.delete_expired_refresh_sessions(db, now)
    token = create_refresh_token()
    await user_repository.create_refresh_session(
        db,
        RefreshSession(
            user_id=user.id,
            token_hash=hash_refresh_token(token),
            expires_at=now + timedelta(days=settings.refresh_token_expires_days),
        ),
    )
    return token


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

    for membership, workspace in await user_repository.list_workspace_scope_rows(db, user_ids):
        workspaces_by_user.setdefault(membership.user_id, []).append(
            UserWorkspaceResponse(
                id=workspace.id,
                name=workspace.name,
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

    for membership, team in await user_repository.list_team_scope_rows(db, user_ids):
        teams_by_user.setdefault(membership.user_id, []).append(
            UserTeamResponse(
                id=team.id,
                workspace_id=team.workspace_id,
                name=team.name,
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


async def list_users(
    db: AsyncSession,
    limit: int | None = None,
    offset: int = 0,
) -> list[UserResponse]:
    users = await user_repository.list_users(db, limit, offset)
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
    user = await user_repository.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return user


async def ensure_user_is_not_last_active_workspace_admin(
    db: AsyncSession,
    user: User,
) -> None:
    if not user.is_active:
        return

    admin_workspace_ids = await user_repository.list_admin_workspace_ids_for_user(db, user.id)
    if not admin_workspace_ids:
        return

    active_admin_counts = await user_repository.active_admin_counts_by_workspace(
        db,
        admin_workspace_ids,
    )
    if any(
        active_admin_counts.get(workspace_id, 0) <= 1
        for workspace_id in admin_workspace_ids
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Workspace must keep at least one active admin.",
        )


async def create_user(
    db: AsyncSession,
    payload: UserCreateRequest,
    actor: User,
    settings: Settings,
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
        workspace = await workspace_repository.get_workspace_by_id(db, payload.workspace_id)
        if workspace is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
        if workspace.status != "active":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace is not active.")

    if team_ids and workspace:
        for team_id in team_ids:
            team = await team_repository.get_team_by_id(db, team_id)
            if team is not None:
                teams.append(team)
        if len(teams) != len(team_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found.")
        if any(team.workspace_id != workspace.id for team in teams):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Teams must belong to selected workspace.",
            )

    initial_password = settings.managed_user_initial_password
    user = User(
        username=normalize_username(payload.username),
        email=normalize_email(payload.email),
        name=normalize_name(payload.name),
        password_hash=hash_password(initial_password),
        is_global_admin=payload.is_global_admin,
        must_change_password=True,
    )

    try:
        user = await user_repository.create_user(db, user)
        if workspace:
            await user_repository.create_workspace_membership(
                db,
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role="member",
                ),
            )
        for team in teams:
            await user_repository.create_team_membership(
                db,
                TeamMembership(
                    workspace_id=team.workspace_id,
                    team_id=team.id,
                    user_id=user.id,
                    role="member",
                ),
            )
        record_audit_log(
            db,
            actor,
            "user.create",
            "user",
            user.id,
            user.name,
            {
                "username": user.username,
                "email": user.email,
                "is_global_admin": user.is_global_admin,
                "workspace_id": workspace.id if workspace else None,
                "team_ids": [team.id for team in teams],
            },
            workspace_id=workspace.id if workspace else None,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Username or email already exists.",
        ) from exc

    user = await user_repository.refresh_user(db, user)
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
    details = payload.model_dump(exclude_none=True)
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
        if not payload.is_active:
            await ensure_user_is_not_last_active_workspace_admin(db, user)
            await user_repository.delete_refresh_sessions_for_user(db, user.id)
        user.is_active = payload.is_active

    record_audit_log(db, actor, "user.update", "user", user.id, user.name, details)

    try:
        user = await user_repository.save_user(db, user)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Username or email already exists.",
        ) from exc

    user = await user_repository.refresh_user(db, user)
    return await user_to_response_with_scopes(db, user)


async def change_user_password(
    db: AsyncSession,
    user: User,
    actor: User,
    new_password: str,
) -> UserResponse:
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await user_repository.delete_refresh_sessions_for_user(db, user.id)
    user = await user_repository.save_user(db, user)
    record_audit_log(db, actor, "user.change_password", "user", user.id, user.name)
    await db.commit()
    user = await user_repository.refresh_user(db, user)
    return await user_to_response_with_scopes(db, user)


async def delete_user_permanently(db: AsyncSession, user: User, actor: User) -> None:
    if user.id == actor.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Current user cannot be deleted.",
        )
    await ensure_user_is_not_last_active_workspace_admin(db, user)
    user = await user_repository.lock_user(db, user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if await agent_repository.has_agent_publication_audit_references(db, user.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "User is retained by Agent publication audit records.",
        )
    if await tools_repository.has_retained_user_audit_references(db, user.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "User is retained by Tool binding or invocation audit records, or a draft.",
        )
    record_audit_log(
        db,
        actor,
        "user.delete",
        "user",
        user.id,
        user.name,
        {"username": user.username, "email": user.email},
    )
    await queue_upload_cleanups(db, uploaded_by_user_id=user.id)
    await delete_owned_mcp_servers_for_user(db, user.id, actor)
    await user_repository.delete_user_graph(db, user.id)
    await db.commit()


async def authenticate_user(
    db: AsyncSession,
    username: str,
    password: str,
    settings: Settings,
    ip_address: str | None = None,
) -> tuple[TokenResponse, str]:
    username = normalize_username(username)
    try:
        await enforce_login_rate_limit(settings, username, ip_address)
    except LoginRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many login attempts.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except LoginRateLimitUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Login rate limiter is unavailable.",
        ) from exc
    user = await user_repository.get_active_user_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        log_event(
            logger,
            logging.WARNING,
            "Login failed.",
            username=username,
            ip_address=ip_address or "",
            reason="invalid_credentials",
        )
        record_system_log(
            db,
            level="warning",
            event="auth.login_failed",
            message="Login failed.",
            path="/api/v1/auth/login",
            method="POST",
            status_code=status.HTTP_401_UNAUTHORIZED,
            user_id=user.id if user else None,
            username=username,
            ip_address=ip_address,
            details={"username": username},
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials.")

    refresh_token = await issue_refresh_session(db, user, settings)
    await db.commit()
    log_event(
        logger,
        logging.INFO,
        "Login succeeded.",
        user_id=user.id,
        username=user.username,
        ip_address=ip_address or "",
    )
    return access_token_response(user, settings), refresh_token


async def refresh_access_token(
    db: AsyncSession,
    refresh_token: str,
    settings: Settings,
) -> TokenResponse:
    session = await user_repository.get_active_refresh_session(
        db,
        hash_refresh_token(refresh_token),
        utc_now(),
    )
    if session is None:
        log_event(logger, logging.WARNING, "Refresh token rejected.", reason="invalid_token")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token.")

    user = await user_repository.get_user_by_id(db, session.user_id)
    if user is None or not user.is_active:
        log_event(
            logger,
            logging.WARNING,
            "Refresh token rejected.",
            reason="user_inactive",
            user_id=session.user_id,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token.")
    log_event(
        logger,
        logging.INFO,
        "Refresh token accepted.",
        user_id=user.id,
        username=user.username,
    )
    return access_token_response(user, settings)


async def revoke_refresh_token(db: AsyncSession, refresh_token: str | None) -> None:
    if refresh_token:
        await user_repository.delete_refresh_session(db, hash_refresh_token(refresh_token))
    await db.commit()


async def change_password(
    db: AsyncSession,
    user: User,
    new_password: str,
    settings: Settings,
    current_password: str | None = None,
) -> str:
    if not current_password or not verify_password(current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is invalid.")
    if verify_password(new_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must be different.")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await user_repository.delete_refresh_sessions_for_user(db, user.id)
    user = await user_repository.save_user(db, user)
    refresh_token = await issue_refresh_session(db, user, settings)
    await db.commit()
    log_event(
        logger,
        logging.INFO,
        "Password changed.",
        user_id=user.id,
        username=user.username,
    )
    return refresh_token


async def get_me(db: AsyncSession, user: User) -> MeResponse:
    membership_list = await user_repository.list_workspace_memberships_for_user(db, user.id)
    return MeResponse(
        user=await user_to_response_with_scopes(db, user),
        memberships=[
            MembershipResponse(workspace_id=item.workspace_id, role=item.role)
            for item in membership_list
        ],
    )


async def find_user_by_identity(db: AsyncSession, username: str, email: str) -> User | None:
    username = normalize_username(username)
    email = normalize_email(email)
    users = await user_repository.find_users_by_identity(db, username, email)
    if not users:
        return None
    if len(users) == 1 and users[0].username == username and users[0].email == email:
        return users[0]
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "Username and email must identify the same user.",
    )
