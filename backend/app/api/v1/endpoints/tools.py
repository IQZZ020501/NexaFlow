"""Unified Tool catalog and Python Tool endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    WorkspaceContext,
    get_db,
    get_settings,
    get_workspace_context_from_path,
)
from app.application.tools import (
    create_python,
    delete_python,
    get_python_test,
    get_tool,
    list_permissions,
    list_tools,
    publish_python,
    queue_python_test,
    revoke_permission,
    set_python_enabled,
    update_policy,
    update_python_draft,
    upsert_permission,
)
from app.schemas.tool import (
    PythonToolCreateRequest,
    PythonToolDraftUpdateRequest,
    ToolDetailResponse,
    ToolDraftResponse,
    ToolInvocationResponse,
    ToolPermissionResponse,
    ToolPermissionUpsertRequest,
    ToolPolicyUpdateRequest,
    ToolSummaryResponse,
    ToolTestRequest,
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


@router.post(
    "/python",
    response_model=ToolDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_python_tool(
    payload: PythonToolCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolDetailResponse:
    return await create_python(
        db,
        context.workspace.id,
        payload,
        context.user,
        context.membership_role,
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


@router.put("/{tool_id}/draft", response_model=ToolDraftResponse)
async def update_workspace_python_tool_draft(
    tool_id: str,
    payload: PythonToolDraftUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolDraftResponse:
    return await update_python_draft(
        db,
        context.workspace.id,
        tool_id,
        payload,
        context.user,
        context.membership_role,
    )


@router.post(
    "/{tool_id}/tests",
    response_model=ToolInvocationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def test_workspace_python_tool(
    tool_id: str,
    payload: ToolTestRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Any, Depends(get_settings)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolInvocationResponse:
    return await queue_python_test(
        db,
        context.workspace.id,
        tool_id,
        payload.arguments,
        context.user,
        context.membership_role,
        settings,
    )


@router.get(
    "/{tool_id}/tests/{invocation_id}",
    response_model=ToolInvocationResponse,
)
async def get_workspace_python_tool_test(
    tool_id: str,
    invocation_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolInvocationResponse:
    return await get_python_test(
        db,
        context.workspace.id,
        tool_id,
        invocation_id,
        context.user,
        context.membership_role,
    )


@router.post("/{tool_id}/publish", response_model=ToolDetailResponse)
async def publish_workspace_python_tool(
    tool_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolDetailResponse:
    return await publish_python(
        db,
        context.workspace.id,
        tool_id,
        context.user,
        context.membership_role,
    )


@router.post("/{tool_id}/disable", response_model=ToolDetailResponse)
async def disable_workspace_python_tool(
    tool_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolDetailResponse:
    return await set_python_enabled(
        db,
        context.workspace.id,
        tool_id,
        False,
        context.user,
        context.membership_role,
    )


@router.post("/{tool_id}/enable", response_model=ToolDetailResponse)
async def enable_workspace_python_tool(
    tool_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolDetailResponse:
    return await set_python_enabled(
        db,
        context.workspace.id,
        tool_id,
        True,
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


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_python_tool(
    tool_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> Response:
    await delete_python(
        db,
        context.workspace.id,
        tool_id,
        context.user,
        context.membership_role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
