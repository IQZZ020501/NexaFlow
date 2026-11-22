from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.api.deps import (
    AppSettingsDep,
    DbSessionDep,
    WorkspaceContext,
    get_workspace_context_from_path,
)
from app.application.tools import integrations
from app.schemas.tools.integrations import (
    IntegrationAuthorizeResponse,
    IntegrationCallbackRequest,
    IntegrationProvider,
    IntegrationResponse,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/integrations", tags=["integrations"]
)
Context = Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)]


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(context: Context, db: DbSessionDep):
    return await integrations.list_integrations(db, context.workspace.id, context.user)


@router.post("/{provider}/authorize", response_model=IntegrationAuthorizeResponse)
async def authorize_integration(
    provider: IntegrationProvider,
    context: Context,
    db: DbSessionDep,
    settings: AppSettingsDep,
    origin: Annotated[str | None, Header(max_length=2048)] = None,
):
    return await integrations.authorize(
        db,
        context.workspace.id,
        context.user,
        provider,
        settings,
        browser_origin=origin,
    )


@router.post("/{provider}/callback", response_model=IntegrationResponse)
async def complete_integration(
    provider: IntegrationProvider,
    payload: IntegrationCallbackRequest,
    context: Context,
    db: DbSessionDep,
    settings: AppSettingsDep,
):
    return await integrations.callback(
        db, context.workspace.id, context.user, provider, payload, settings
    )


@router.delete("/{provider}", response_model=IntegrationResponse)
async def uninstall_integration(
    provider: IntegrationProvider, context: Context, db: DbSessionDep
):
    return await integrations.uninstall(
        db, context.workspace.id, context.user, provider
    )


@router.post("/{provider}/sync", response_model=IntegrationResponse)
async def sync_integration_tools(
    provider: IntegrationProvider, context: Context, db: DbSessionDep
):
    return await integrations.sync_tools(
        db, context.workspace.id, context.user, provider
    )
