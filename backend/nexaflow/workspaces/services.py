import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from nexaflow.audit.services import record_audit_log
from nexaflow.core.validation import normalize_email, normalize_name, normalize_username
from nexaflow.db.model_utils import new_id
from nexaflow.identity.models import User
from nexaflow.identity.schemas import UserCreateRequest, UserPasswordResetResponse
from nexaflow.identity.security import hash_password
from nexaflow.identity.services import create_user, find_user_by_identity, user_to_response
from nexaflow.teams.models import Team
from nexaflow.workspaces.models import Workspace, WorkspaceMembership
from nexaflow.workspaces import repositories as workspace_repository
from nexaflow.workspaces.schemas import (
    WorkspaceMemberResponse,
    WorkspaceUserCreateRequest,
    WorkspaceCreateRequest,
    WorkspaceCreateResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)

ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
WORKSPACE_STATUSES = {ACTIVE_STATUS, ARCHIVED_STATUS}
WORKSPACE_MEMBER_ROLES = {"admin", "member"}


def workspace_to_response(workspace: Workspace) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        status=workspace.status,
        is_default=workspace.is_default,
    )


def workspace_member_to_response(
    membership: WorkspaceMembership,
    user: User,
) -> WorkspaceMemberResponse:
    return WorkspaceMemberResponse(
        user=user_to_response(user),
        role=membership.role,
    )


def validate_workspace_member_role(role: str) -> None:
    if role not in WORKSPACE_MEMBER_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid workspace role.")


async def count_workspace_admins(db: AsyncSession, workspace_id: str) -> int:
    return await workspace_repository.count_workspace_admins(db, workspace_id)


async def ensure_not_last_workspace_admin(
    db: AsyncSession,
    membership: WorkspaceMembership,
) -> None:
    if membership.role != "admin":
        return
    if await count_workspace_admins(db, membership.workspace_id) <= 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Workspace must keep at least one admin.",
        )


async def list_workspaces(db: AsyncSession, user: User) -> list[WorkspaceResponse]:
    if user.is_global_admin:
        workspaces = await workspace_repository.list_all_workspaces(db)
    else:
        workspaces = await workspace_repository.list_workspaces_for_user(db, user.id)
    return [workspace_to_response(item) for item in workspaces]


async def get_workspace_for_user(db: AsyncSession, workspace_id: str, user: User) -> Workspace:
    workspace = await workspace_repository.get_workspace_by_id(db, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    if user.is_global_admin:
        return workspace

    membership = await workspace_repository.get_workspace_membership(db, workspace_id, user.id)
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace access denied.")
    return workspace


async def create_workspace(
    db: AsyncSession,
    payload: WorkspaceCreateRequest,
    actor: User,
) -> WorkspaceCreateResponse:
    username = normalize_username(payload.admin.username)
    email = normalize_email(payload.admin.email)
    admin_name = normalize_name(payload.admin.name)
    workspace_name = normalize_name(payload.name)
    workspace_description = payload.description.strip()
    workspace_slug = new_id()

    admin = await find_user_by_identity(db, username, email)
    admin_created = admin is None
    initial_password: str | None = None
    if admin is None:
        initial_password = secrets.token_urlsafe(18)
        admin = User(
            username=username,
            email=email,
            name=admin_name,
            password_hash=hash_password(initial_password),
            must_change_password=True,
            is_global_admin=False,
        )
        db.add(admin)

    workspace = Workspace(
        name=workspace_name,
        description=workspace_description,
        slug=workspace_slug,
        status=ACTIVE_STATUS,
    )
    db.add(workspace)

    try:
        await db.flush()
        db.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=admin.id,
                role="admin",
            )
        )
        record_audit_log(
            db,
            actor,
            "workspace.create",
            "workspace",
            workspace.id,
            workspace.name,
            {"description": workspace.description},
            workspace_id=workspace.id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Workspace already exists.") from exc

    await db.refresh(workspace)
    await db.refresh(admin)
    return WorkspaceCreateResponse(
        workspace=workspace_to_response(workspace),
        admin_user=user_to_response(admin),
        admin_created=admin_created,
        admin_initial_password=initial_password,
    )


async def update_workspace(
    db: AsyncSession,
    workspace: Workspace,
    payload: WorkspaceUpdateRequest,
    actor: User,
) -> WorkspaceResponse:
    details = payload.model_dump(exclude_none=True)
    if payload.name is not None:
        workspace.name = normalize_name(payload.name)
    if payload.description is not None:
        workspace.description = payload.description.strip()
    if payload.status is not None:
        if payload.status not in WORKSPACE_STATUSES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid workspace status.")
        if workspace.is_default and payload.status == ARCHIVED_STATUS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Default workspace cannot be archived.")
        workspace.status = payload.status

    action = "workspace.update"
    if set(details) == {"status"} and payload.status == ARCHIVED_STATUS:
        action = "workspace.archive"
    elif set(details) == {"status"} and payload.status == ACTIVE_STATUS:
        action = "workspace.restore"
    record_audit_log(
        db,
        actor,
        action,
        "workspace",
        workspace.id,
        workspace.name,
        details,
        workspace_id=workspace.id,
    )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Workspace already exists.") from exc

    await db.refresh(workspace)
    return workspace_to_response(workspace)


async def list_workspace_members(
    db: AsyncSession,
    workspace: Workspace,
) -> list[WorkspaceMemberResponse]:
    return [
        workspace_member_to_response(membership, user)
        for membership, user in await workspace_repository.list_workspace_member_rows(db, workspace.id)
    ]


async def get_workspace_member(
    db: AsyncSession,
    workspace: Workspace,
    user_id: str,
) -> tuple[WorkspaceMembership, User]:
    row = await workspace_repository.get_workspace_member_row(db, workspace.id, user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")
    membership, user = row
    return membership, user


async def add_workspace_member(
    db: AsyncSession,
    workspace: Workspace,
    user_id: str,
    role: str,
    actor: User,
) -> WorkspaceMemberResponse:
    validate_workspace_member_role(role)
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add(membership)
    record_audit_log(
        db,
        actor,
        "workspace.member.add",
        "workspace_member",
        user.id,
        user.name,
        {"role": role},
        workspace_id=workspace.id,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Workspace member already exists.",
        ) from exc

    return workspace_member_to_response(membership, user)


async def create_workspace_user(
    db: AsyncSession,
    workspace: Workspace,
    payload: WorkspaceUserCreateRequest,
    actor: User,
) -> UserPasswordResetResponse:
    return await create_user(
        db,
        UserCreateRequest(
            username=payload.username,
            email=payload.email,
            name=payload.name,
            is_global_admin=False,
            workspace_id=workspace.id,
            team_ids=[],
        ),
        actor,
    )


async def update_workspace_member_role(
    db: AsyncSession,
    workspace: Workspace,
    user_id: str,
    role: str,
    actor: User,
) -> WorkspaceMemberResponse:
    validate_workspace_member_role(role)
    membership, user = await get_workspace_member(db, workspace, user_id)
    if role != "admin":
        await ensure_not_last_workspace_admin(db, membership)
    previous_role = membership.role
    membership.role = role
    record_audit_log(
        db,
        actor,
        "workspace.member.update",
        "workspace_member",
        user.id,
        user.name,
        {"previous_role": previous_role, "role": role},
        workspace_id=workspace.id,
    )
    await db.commit()
    await db.refresh(membership)
    return workspace_member_to_response(membership, user)


async def remove_workspace_member(
    db: AsyncSession,
    workspace: Workspace,
    user_id: str,
    actor: User,
) -> None:
    membership, user = await get_workspace_member(db, workspace, user_id)
    await ensure_not_last_workspace_admin(db, membership)
    record_audit_log(
        db,
        actor,
        "workspace.member.remove",
        "workspace_member",
        user.id,
        user.name,
        {"role": membership.role},
        workspace_id=workspace.id,
    )
    await workspace_repository.delete_workspace_member_graph(db, workspace.id, user.id)
    await db.commit()


async def delete_workspace_permanently(
    db: AsyncSession,
    workspace: Workspace,
    actor: User,
) -> None:
    if workspace.is_default:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Default workspace cannot be deleted.")

    record_audit_log(
        db,
        actor,
        "workspace.delete",
        "workspace",
        workspace.id,
        workspace.name,
        {"description": workspace.description},
        workspace_id=workspace.id,
    )
    await workspace_repository.delete_workspace_graph(db, workspace.id)
    await db.commit()
