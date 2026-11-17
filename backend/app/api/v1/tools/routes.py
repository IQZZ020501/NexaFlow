"""Unified Tool catalog endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    WorkspaceContext,
    get_db,
    get_workspace_context_from_path,
)
from app.application.tools import (
    get_tool,
    list_permissions,
    list_tools,
    revoke_permission,
    update_policy,
    upsert_permission,
)
from app.schemas.tools.contracts import (
    ToolDetailResponse,
    ToolPermissionResponse,
    ToolPermissionUpsertRequest,
    ToolPolicyUpdateRequest,
    ToolSummaryResponse,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/tools",
    tags=["tools"],
)


@router.get("", response_model=list[ToolSummaryResponse])
async def list_workspace_tools(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ToolSummaryResponse]:
    return await list_tools(
        db,
        context.workspace.id,
        context.user,
        context.membership_role,
        limit,
        offset,
    )


@router.get("/{tool_id}", response_model=ToolDetailResponse)
async def get_workspace_tool(
    tool_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolDetailResponse:
    return await get_tool(
        db,
        context.workspace.id,
        tool_id,
        context.user,
        context.membership_role,
    )


@router.put("/{tool_id}/policy", response_model=ToolDetailResponse)
async def update_workspace_tool_policy(
    tool_id: str,
    payload: ToolPolicyUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolDetailResponse:
    return await update_policy(
        db,
        context.workspace.id,
        tool_id,
        payload.mode,
        context.user,
        context.membership_role,
    )


@router.get(
    "/{tool_id}/permissions",
    response_model=list[ToolPermissionResponse],
)
async def list_workspace_tool_permissions(
    tool_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ToolPermissionResponse]:
    return await list_permissions(
        db,
        context.workspace.id,
        tool_id,
        context.user,
        context.membership_role,
        limit,
        offset,
    )


@router.put(
    "/{tool_id}/permissions/{user_id}",
    response_model=ToolPermissionResponse,
)
async def upsert_workspace_tool_permission(
    tool_id: str,
    user_id: str,
    payload: ToolPermissionUpsertRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolPermissionResponse:
    return await upsert_permission(
        db,
        context.workspace.id,
        tool_id,
        user_id,
        payload.permission,
        context.user,
        context.membership_role,
    )


@router.delete(
    "/{tool_id}/permissions/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_workspace_tool_permission(
    tool_id: str,
    user_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> Response:
    await revoke_permission(
        db,
        context.workspace.id,
        tool_id,
        user_id,
        context.user,
        context.membership_role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
