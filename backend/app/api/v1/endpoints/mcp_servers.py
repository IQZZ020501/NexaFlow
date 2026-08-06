from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
    require_workspace_path_role,
)
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.application.tools import (
    create_mcp_server,
    delete_mcp_server,
    get_mcp_server,
    list_mcp_servers,
    refresh_mcp_server,
)
from app.schemas.mcp import McpServerCreateRequest, McpServerResponse

router = APIRouter(
    prefix="/workspaces/{workspace_id}/mcp-servers",
    tags=["mcp"],
)


@router.get("", response_model=list[McpServerResponse])
async def list_workspace_mcp_servers(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[McpServerResponse]:
    return await list_mcp_servers(db, context.workspace.id, limit, offset)


@router.post(
    "",
    response_model=McpServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_mcp_server(
    payload: McpServerCreateRequest,
    context: Annotated[
        WorkspaceContext,
        Depends(require_workspace_path_role({"admin"})),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> McpServerResponse:
    return await create_mcp_server(
        db,
        context.workspace.id,
        payload,
        context.user,
        settings,
    )


@router.post("/{server_id}/refresh", response_model=McpServerResponse)
async def refresh_workspace_mcp_server(
    server_id: str,
    context: Annotated[
        WorkspaceContext,
        Depends(require_workspace_path_role({"admin"})),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> McpServerResponse:
    server = await get_mcp_server(db, context.workspace.id, server_id)
    return await refresh_mcp_server(db, server, context.user, settings)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_mcp_server(
    server_id: str,
    context: Annotated[
        WorkspaceContext,
        Depends(require_workspace_path_role({"admin"})),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    server = await get_mcp_server(db, context.workspace.id, server_id)
    await delete_mcp_server(db, server, context.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
