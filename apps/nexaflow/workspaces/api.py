from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.audit.schemas import AuditLogResponse
from nexaflow.audit.services import list_workspace_audit_logs
from nexaflow.db.session import get_db
from nexaflow.identity.deps import (
    WorkspaceContext,
    get_workspace_context_from_path,
    require_global_admin,
    require_password_changed,
    require_workspace_path_role,
)
from nexaflow.identity.models import User
from nexaflow.identity.schemas import UserPasswordResetResponse
from nexaflow.workspaces.schemas import (
    WorkspaceMemberCreateRequest,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdateRequest,
    WorkspaceUserCreateRequest,
    WorkspaceCreateRequest,
    WorkspaceCreateResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)
from nexaflow.workspaces.services import (
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
) -> list[WorkspaceResponse]:
    return await list_workspaces(db, user)


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
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    workspace = await get_workspace_for_user(db, workspace_id, actor)
    await delete_workspace_permanently(db, workspace, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
async def list_members(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkspaceMemberResponse]:
    return await list_workspace_members(db, context.workspace)


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
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPasswordResetResponse:
    return await create_workspace_user(db, context.workspace, payload, context.user)


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
) -> list[AuditLogResponse]:
    return await list_workspace_audit_logs(db, context.workspace.id, limit)
