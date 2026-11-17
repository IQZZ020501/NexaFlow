from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_settings, get_workspace_context_from_path
from app.application.tools import oauth
from app.infra.config.settings import Settings
from app.infra.db.session import get_db
from app.schemas.tools.oauth import (
    McpOAuthAuthorization,
    McpOAuthCallback,
    McpOAuthConfiguration,
    McpOAuthStatus,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/mcp-servers", tags=["mcp"])
Context = Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)]
Database = Annotated[AsyncSession, Depends(get_db)]
Configuration = Annotated[Settings, Depends(get_settings)]


@router.get("/{server_id}/oauth", response_model=McpOAuthStatus)
async def oauth_status(server_id: str, context: Context, db: Database):
    return await oauth.status(
        db, context.workspace.id, server_id, context.user, context.membership_role
    )


@router.put("/{server_id}/oauth", response_model=McpOAuthStatus)
async def configure_oauth(
    server_id: str,
    payload: McpOAuthConfiguration,
    context: Context,
    db: Database,
    settings: Configuration,
):
    return await oauth.configure(
        db,
        context.workspace.id,
        server_id,
        context.user,
        context.membership_role,
        payload,
        settings,
    )


@router.post("/{server_id}/oauth/authorize", response_model=McpOAuthAuthorization)
async def authorize_oauth(
    server_id: str, context: Context, db: Database, settings: Configuration
):
    return await oauth.authorize(
        db,
        context.workspace.id,
        server_id,
        context.user,
        context.membership_role,
        settings,
    )


@router.post("/{server_id}/oauth/callback", response_model=McpOAuthStatus)
async def oauth_callback(
    server_id: str,
    payload: McpOAuthCallback,
    context: Context,
    db: Database,
    settings: Configuration,
):
    return await oauth.callback(
        db,
        context.workspace.id,
        server_id,
        context.user,
        context.membership_role,
        payload,
        settings,
    )


@router.post("/{server_id}/oauth/disconnect", response_model=McpOAuthStatus)
async def disconnect_oauth(server_id: str, context: Context, db: Database):
    return await oauth.disconnect(
        db, context.workspace.id, server_id, context.user, context.membership_role
    )
