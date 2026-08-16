import logging
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from app.infrastructure.config import Settings
from app.infrastructure.logger import get_logger, log_event

logger = get_logger(__name__)

from app.shareddomain.audit.services import record_audit_log
from app.infrastructure.validation import normalize_name
from app.infrastructure.model_utils import new_id
from app.entities.user import User
from app.schemas.user import UserCreateRequest, UserPasswordResetResponse
from app.application.identity import create_user
from app.schemas.user import user_to_response
from app.entities.workspace import WORKSPACE_MEMBER_ROLES, Workspace, WorkspaceMembership
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import mcp as mcp_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workspace as workspace_repository
from app.ports import model_registry
from app.shareddomain.knowledge.services import delete_workspace_knowledge_bases
from app.shareddomain.tools.catalog import ensure_workspace_system_catalog
from app.shareddomain.workflows.uploads import queue_upload_cleanups
from app.tasks.knowledge import enqueue_knowledge_storage_cleanup
from app.tasks.knowledge import enqueue_upload_storage_cleanups
from app.schemas.workspace import (
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


@dataclass(frozen=True)
class WorkspaceContext:
    workspace: Workspace
    user: User
    membership_role: str | None


async def build_workspace_context(
    db: AsyncSession,
    user: User,
    workspace_id: str,
) -> WorkspaceContext:
    workspace = await workspace_repository.get_workspace_by_id(db, workspace_id)
    if workspace is None:
        log_event(
            logger,
            logging.WARNING,
            "Workspace context failed.",
            reason="not_found",
            user_id=user.id,
            workspace_id=workspace_id,
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    if workspace.status != ACTIVE_STATUS:
        log_event(
            logger,
            logging.WARNING,
            "Workspace context failed.",
            reason="inactive",
            user_id=user.id,
            workspace_id=workspace_id,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace is not active.")

    membership = await workspace_repository.get_workspace_membership(db, workspace_id, user.id)
    if membership is None:
        if user.is_global_admin:
            return WorkspaceContext(
                workspace=workspace,
                user=user,
                membership_role="admin",
            )
        log_event(
            logger,
            logging.WARNING,
            "Workspace access denied.",
            user_id=user.id,
            workspace_id=workspace_id,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace access denied.")

    return WorkspaceContext(
        workspace=workspace,
        user=user,
        membership_role=membership.role if membership else None,
    )


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


def require_global_admin_for_workspace_admin(actor: User) -> None:
    if not actor.is_global_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Global admin required to manage workspace admins.",
        )


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


async def list_workspaces(
    db: AsyncSession,
    user: User,
    limit: int | None = None,
    offset: int = 0,
) -> list[WorkspaceResponse]:
    if user.is_global_admin:
        workspaces = await workspace_repository.list_all_workspaces(db, limit, offset)
    else:
        workspaces = await workspace_repository.list_workspaces_for_user(
            db,
            user.id,
            limit,
            offset,
        )
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
    admin = await user_repository.get_user_by_id(db, payload.admin_user_id)
    if admin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if not admin.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Workspace admin must be active.",
        )

    workspace_name = normalize_name(payload.name)
    workspace_description = payload.description.strip()
    workspace_slug = new_id()

    workspace = Workspace(
        name=workspace_name,
        description=workspace_description,
        slug=workspace_slug,
        status=ACTIVE_STATUS,
    )

    try:
        workspace = await workspace_repository.create_workspace(db, workspace)
        await workspace_repository.create_workspace_membership(
            db,
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=admin.id,
                role="admin",
            ),
        )
        await ensure_workspace_system_catalog(db, workspace.id)
        record_audit_log(
            db,
            actor,
            "workspace.create",
            "workspace",
            workspace.id,
            workspace.name,
            {
                "description": workspace.description,
                "admin_user_id": admin.id,
            },
            workspace_id=workspace.id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Workspace already exists.") from exc

    workspace = await workspace_repository.refresh_workspace(db, workspace)
    return WorkspaceCreateResponse(
        workspace=workspace_to_response(workspace),
        admin_user=user_to_response(admin),
    )


async def update_workspace(
    db: AsyncSession,
    workspace: Workspace,
    payload: WorkspaceUpdateRequest,
    actor: User,
) -> WorkspaceResponse:
    workspace = await workspace_repository.lock_workspace(db, workspace.id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    details = payload.model_dump(exclude_none=True)
    if payload.name is not None:
        workspace.name = normalize_name(payload.name)
    if payload.description is not None:
        workspace.description = payload.description.strip()
    if payload.status is not None:
        if payload.status not in WORKSPACE_STATUSES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid workspace status.")
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
        workspace = await workspace_repository.save_workspace(db, workspace)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Workspace already exists.") from exc

    workspace = await workspace_repository.refresh_workspace(db, workspace)
    return workspace_to_response(workspace)


async def list_workspace_members(
    db: AsyncSession,
    workspace: Workspace,
    limit: int | None = None,
    offset: int = 0,
) -> list[WorkspaceMemberResponse]:
    return [
        workspace_member_to_response(membership, user)
        for membership, user in await workspace_repository.list_workspace_member_rows(
            db,
            workspace.id,
            limit,
            offset,
        )
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
    if role == "admin":
        require_global_admin_for_workspace_admin(actor)
    user = await user_repository.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
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
        membership = await workspace_repository.create_workspace_membership(
            db,
            membership,
        )
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
    settings: Settings,
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
        settings,
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
    if role == "admin" or membership.role == "admin":
        require_global_admin_for_workspace_admin(actor)
    if role != "admin":
        await ensure_not_last_workspace_admin(db, membership)
    previous_role = membership.role
    membership.role = role
    membership = await workspace_repository.save_workspace_membership(db, membership)
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
    membership = await workspace_repository.refresh_workspace_membership(db, membership)
    return workspace_member_to_response(membership, user)


async def remove_workspace_member(
    db: AsyncSession,
    workspace: Workspace,
    user_id: str,
    actor: User,
) -> None:
    membership, user = await get_workspace_member(db, workspace, user_id)
    if membership.role == "admin":
        require_global_admin_for_workspace_admin(actor)
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
    settings: Settings,
) -> None:
    workspace = await workspace_repository.lock_workspace(db, workspace.id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")

    cleanup_ids = await delete_workspace_knowledge_bases(
        db,
        workspace.id,
    )
    upload_cleanup_ids = await queue_upload_cleanups(
        db,
        workspace_id=workspace.id,
    )
    record_audit_log(
        db,
        actor,
        "workspace.delete",
        "workspace",
        workspace.id,
        workspace.name,
        {
            "description": workspace.description,
            "knowledge_base_count": len(cleanup_ids),
        },
        workspace_id=workspace.id,
    )
    await agent_repository.delete_workspace_agent_graph(db, workspace.id)
    await mcp_repository.delete_workspace_mcp_servers(db, workspace.id)
    await model_registry.delete_registered_models_in_workspace(db, workspace.id)
    await workspace_repository.delete_workspace_graph(db, workspace.id)
    await db.commit()
    for cleanup_id in cleanup_ids:
        await enqueue_knowledge_storage_cleanup(cleanup_id, settings)
    await enqueue_upload_storage_cleanups(upload_cleanup_ids, settings)
