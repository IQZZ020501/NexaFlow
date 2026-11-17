from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_workspace_context_from_path
from app.application.tools import remote_task_configuration as use_case
from app.infra.db.session import get_db
from app.schemas.tools.tasks import McpTaskConfiguration, McpTaskConfigurationResponse

router = APIRouter(prefix="/workspaces/{workspace_id}/mcp-servers", tags=["mcp"])
Context = Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)]
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("/{server_id}/long-tasks", response_model=McpTaskConfigurationResponse)
async def task_configuration(server_id: str, context: Context, db: Database):
    return await use_case.configuration(
        db, context.workspace.id, server_id, context.user, context.membership_role
    )


@router.put("/{server_id}/long-tasks", response_model=McpTaskConfigurationResponse)
async def configure_tasks(
    server_id: str, payload: McpTaskConfiguration, context: Context, db: Database
):
    return await use_case.configure(
        db,
        context.workspace.id,
        server_id,
        context.user,
        context.membership_role,
        payload,
    )
