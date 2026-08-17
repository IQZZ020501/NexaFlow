"""Unified Tool source lifecycle endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    WorkspaceContext,
    get_db,
    get_settings,
    get_workspace_context_from_path,
)
from app.application.tools import (
    create_mcp_source,
    delete_source,
    list_sources,
    refresh_source,
    set_source_enabled,
)
from app.schemas.mcp import McpServerCreateRequest
from app.schemas.tool import ToolSourceDetailResponse

router = APIRouter(
    prefix="/workspaces/{workspace_id}/tool-sources",
    tags=["tool-sources"],
)


@router.get("", response_model=list[ToolSourceDetailResponse])
async def list_workspace_tool_sources(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ToolSourceDetailResponse]:
    return await list_sources(
        db,
        context.workspace.id,
        context.user,
        context.membership_role,
        limit,
        offset,
    )


@router.post(
    "/mcp",
    response_model=ToolSourceDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_mcp_source(
    payload: McpServerCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Any, Depends(get_settings)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolSourceDetailResponse:
    return await create_mcp_source(
        db,
        context.workspace.id,
        payload,
        context.user,
        context.membership_role,
        settings,
    )


@router.post("/{source_id}/refresh", response_model=ToolSourceDetailResponse)
async def refresh_workspace_tool_source(
    source_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Any, Depends(get_settings)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolSourceDetailResponse:
    return await refresh_source(
        db,
        context.workspace.id,
        source_id,
        context.user,
        context.membership_role,
        settings,
    )


async def _set_enabled(
    source_id: str,
    enabled: bool,
    context: WorkspaceContext,
    db: Any,
) -> ToolSourceDetailResponse:
    return await set_source_enabled(
        db,
        context.workspace.id,
        source_id,
        enabled,
        context.user,
        context.membership_role,
    )


@router.post("/{source_id}/disable", response_model=ToolSourceDetailResponse)
async def disable_workspace_tool_source(
    source_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolSourceDetailResponse:
    return await _set_enabled(source_id, False, context, db)


@router.post("/{source_id}/enable", response_model=ToolSourceDetailResponse)
async def enable_workspace_tool_source(
    source_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> ToolSourceDetailResponse:
    return await _set_enabled(source_id, True, context, db)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_tool_source(
    source_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[Any, Depends(get_db)],
) -> Response:
    await delete_source(
        db,
        context.workspace.id,
        source_id,
        context.user,
        context.membership_role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
