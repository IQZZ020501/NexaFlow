from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.audit import list_workspace_audit_logs
from app.application.analytics import get_workspace_analytics
from app.application.governance import (
    get_workspace_governance,
    get_workspace_inventory,
    update_workspace_governance,
)
from app.application.invitations import (
    create_workspace_invitation,
    list_workspace_invitations,
    revoke_workspace_invitation,
)
from app.schemas.analytics import WorkspaceAnalyticsResponse
from app.schemas.governance import (
    WorkspaceGovernanceResponse,
    WorkspaceGovernanceUpdateRequest,
    WorkspaceInventoryResponse,
)
from app.schemas.invitation import (
    WorkspaceInvitationCreateRequest,
    WorkspaceInvitationResponse,
)
from app.schemas.audit import AuditLogResponse
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.api.deps import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
    require_global_admin,
    require_password_changed,
    require_workspace_path_role,
)
from app.entities.user import User
from app.schemas.user import UserPasswordResetResponse
from app.schemas.workspace import (
    WorkspaceMemberCreateRequest,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdateRequest,
    WorkspaceUserCreateRequest,
    WorkspaceCreateRequest,
    WorkspaceCreateResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)
from app.application.workspace import (
    add_workspace_member,
    create_workspace,
    create_workspace_user,
    delete_workspace_permanently,
    get_workspace_for_user,
    list_workspaces,
    list_workspace_members,
    remove_workspace_member,
    update_workspace,
    update_workspace_member_role,
    workspace_to_response,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_current_workspaces(
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WorkspaceResponse]:
    return await list_workspaces(db, user, limit, offset)


@router.post("", response_model=WorkspaceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_new_workspace(
    payload: WorkspaceCreateRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceCreateResponse:
    return await create_workspace(db, payload, actor)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    return workspace_to_response(await get_workspace_for_user(db, workspace_id, user))


@router.get("/{workspace_id}/analytics", response_model=WorkspaceAnalyticsResponse)
async def read_workspace_analytics(
    context: Annotated[
        WorkspaceContext,
        Depends(require_workspace_path_role({"admin"})),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> WorkspaceAnalyticsResponse:
    return await get_workspace_analytics(
        db,
        context.workspace,
        context.user,
        from_date,
        to_date,
    )


@router.get("/{workspace_id}/governance", response_model=WorkspaceGovernanceResponse)
async def read_workspace_governance(
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceGovernanceResponse:
    return await get_workspace_governance(db, context.workspace.id)


@router.patch("/{workspace_id}/governance", response_model=WorkspaceGovernanceResponse)
async def patch_workspace_governance(
    payload: WorkspaceGovernanceUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceGovernanceResponse:
    return await update_workspace_governance(db, context.workspace, context.user, payload)


@router.get("/{workspace_id}/inventory", response_model=WorkspaceInventoryResponse)
async def read_workspace_inventory(
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceInventoryResponse:
    return await get_workspace_inventory(db, context.workspace.id)


@router.get(
    "/{workspace_id}/invitations",
    response_model=list[WorkspaceInvitationResponse],
)
async def list_invitations(
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkspaceInvitationResponse]:
    return await list_workspace_invitations(db, context.workspace.id)


@router.post(
    "/{workspace_id}/invitations",
    response_model=WorkspaceInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    payload: WorkspaceInvitationCreateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceInvitationResponse:
    return await create_workspace_invitation(db, context.workspace.id, context.user, payload)


@router.delete(
    "/{workspace_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    invitation_id: str,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await revoke_workspace_invitation(db, context.workspace.id, invitation_id, context.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def patch_workspace(
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    workspace = await get_workspace_for_user(db, workspace_id, actor)
    return await update_workspace(db, workspace, payload, actor)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str,
    actor: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    workspace = await get_workspace_for_user(db, workspace_id, actor)
    await delete_workspace_permanently(db, workspace, actor, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
async def list_members(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WorkspaceMemberResponse]:
    return await list_workspace_members(db, context.workspace, limit, offset)


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    payload: WorkspaceMemberCreateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceMemberResponse:
    return await add_workspace_member(
        db,
        context.workspace,
        payload.user_id,
        payload.role,
        context.user,
    )


@router.post(
    "/{workspace_id}/members/users",
    response_model=UserPasswordResetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_member_user(
    payload: WorkspaceUserCreateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPasswordResetResponse:
    return await create_workspace_user(
        db,
        context.workspace,
        payload,
        context.user,
        settings,
    )


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberResponse)
async def patch_member(
    user_id: str,
    payload: WorkspaceMemberUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceMemberResponse:
    return await update_workspace_member_role(
        db,
        context.workspace,
        user_id,
        payload.role,
        context.user,
    )


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(
    user_id: str,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await remove_workspace_member(db, context.workspace, user_id, context.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/audit-logs", response_model=list[AuditLogResponse])
async def list_workspace_logs(
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    actor: Annotated[str | None, Query(max_length=120)] = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    resource_type: Annotated[str | None, Query(max_length=40)] = None,
    resource_id: Annotated[str | None, Query(max_length=36)] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    from_date: Annotated[datetime | None, Query(alias="from")] = None,
    to_date: Annotated[datetime | None, Query(alias="to")] = None,
) -> list[AuditLogResponse]:
    return await list_workspace_audit_logs(
        db,
        context.workspace.id,
        limit,
        offset,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        from_date=from_date,
        to_date=to_date,
    )
