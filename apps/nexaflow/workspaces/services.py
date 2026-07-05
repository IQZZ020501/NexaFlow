import secrets

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from nexaflow.audit.services import record_audit_log
from nexaflow.core.validation import normalize_email, normalize_name, normalize_slug, normalize_username
from nexaflow.identity.models import User
from nexaflow.identity.security import hash_password
from nexaflow.identity.services import find_user_by_identity, user_to_response
from nexaflow.teams.models import Team, TeamMembership
from nexaflow.workspaces.models import Workspace, WorkspaceMembership
from nexaflow.workspaces.schemas import (
    WorkspaceCreateRequest,
    WorkspaceCreateResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)

ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
WORKSPACE_STATUSES = {ACTIVE_STATUS, ARCHIVED_STATUS}


def workspace_to_response(workspace: Workspace) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        status=workspace.status,
        is_default=workspace.is_default,
    )


async def list_workspaces(db: AsyncSession, user: User) -> list[WorkspaceResponse]:
    if user.is_global_admin:
        result = await db.scalars(select(Workspace).order_by(Workspace.created_at))
    else:
        result = await db.scalars(
            select(Workspace)
            .join(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == user.id)
            .order_by(Workspace.created_at)
        )
    workspaces = result.all()
    return [workspace_to_response(item) for item in workspaces]


async def get_workspace_for_user(db: AsyncSession, workspace_id: str, user: User) -> Workspace:
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    if user.is_global_admin:
        return workspace

    membership = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
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
    workspace_slug = normalize_slug(payload.slug)

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

    workspace = Workspace(name=workspace_name, slug=workspace_slug, status=ACTIVE_STATUS)
    db.add(workspace)

    try:
        await db.flush()
        db.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=admin.id,
                role="owner",
            )
        )
        record_audit_log(
            db,
            actor,
            "workspace.create",
            "workspace",
            workspace.id,
            workspace.name,
            {"slug": workspace.slug},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Workspace slug already exists.") from exc

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
    if payload.slug is not None:
        workspace.slug = normalize_slug(payload.slug)
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
    record_audit_log(db, actor, action, "workspace", workspace.id, workspace.name, details)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Workspace slug already exists.") from exc

    await db.refresh(workspace)
    return workspace_to_response(workspace)


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
        {"slug": workspace.slug},
    )
    team_ids = select(Team.id).where(Team.workspace_id == workspace.id)
    await db.execute(delete(TeamMembership).where(TeamMembership.team_id.in_(team_ids)))
    await db.execute(
        delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace.id)
    )
    await db.execute(delete(Team).where(Team.workspace_id == workspace.id))
    await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
    await db.commit()
