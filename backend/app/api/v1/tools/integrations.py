from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    AppSettingsDep,
    DbSessionDep,
    WorkspaceContext,
    get_workspace_context_from_path,
)
from app.application.tools import integrations
from app.schemas.tools.integrations import (
    IntegrationApplicationRequest,
    IntegrationApplicationResponse,
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


@router.get("/{provider}/application", response_model=IntegrationApplicationResponse)
async def get_application(
    provider: IntegrationProvider, context: Context, db: DbSessionDep
):
    return await integrations.application_status(
        db, context.workspace.id, context.user, context.membership_role, provider
    )


@router.put("/{provider}/application", response_model=IntegrationApplicationResponse)
async def configure_application(
    provider: IntegrationProvider,
    payload: IntegrationApplicationRequest,
    context: Context,
    db: DbSessionDep,
    settings: AppSettingsDep,
):
    return await integrations.configure(
        db,
        context.workspace.id,
        context.user,
        context.membership_role,
        provider,
        payload,
        settings,
    )


@router.post("/{provider}/authorize", response_model=IntegrationAuthorizeResponse)
async def authorize_integration(
    provider: IntegrationProvider,
    context: Context,
    db: DbSessionDep,
    settings: AppSettingsDep,
):
    return await integrations.authorize(
        db, context.workspace.id, context.user, provider, settings
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
