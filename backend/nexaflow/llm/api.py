from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.core.config import Settings
from nexaflow.db.session import get_db
from nexaflow.identity.dependencies import (
    WorkspaceContext,
    get_current_user,
    get_settings,
    get_workspace_context_from_path,
    require_workspace_path_role,
)
from nexaflow.identity.models import User
from nexaflow.llm.schemas import (
    BaseModelOptionResponse,
    ModelCredentialFieldResponse,
    ModelProviderCatalogResponse,
    RegisteredModelCreateRequest,
    RegisteredModelResponse,
    RegisteredModelUpdateRequest,
)
from nexaflow.llm.services import (
    create_registered_model,
    delete_registered_model,
    get_model_credential_form,
    get_registered_model,
    list_base_models,
    list_model_types,
    list_provider_catalog,
    list_registered_models,
    model_to_response,
    update_registered_model,
)

router = APIRouter(tags=["llm"])


@router.get("/model-providers", response_model=list[ModelProviderCatalogResponse])
async def list_model_provider_catalog(
    user: Annotated[User, Depends(get_current_user)],
    model_type: str | None = None,
) -> list[ModelProviderCatalogResponse]:
    _ = user
    return list_provider_catalog(model_type)


@router.get("/model-providers/model_type_list", response_model=list[dict[str, str]])
async def list_model_provider_model_types(
    user: Annotated[User, Depends(get_current_user)],
    provider: str,
) -> list[dict[str, str]]:
    _ = user
    return list_model_types(provider)


@router.get("/model-providers/model_list", response_model=list[BaseModelOptionResponse])
async def list_model_provider_base_models(
    user: Annotated[User, Depends(get_current_user)],
    provider: str,
    model_type: str,
) -> list[BaseModelOptionResponse]:
    _ = user
    return list_base_models(provider, model_type)


@router.get("/model-providers/model_form", response_model=list[ModelCredentialFieldResponse])
async def get_model_provider_credential_form(
    user: Annotated[User, Depends(get_current_user)],
    provider: str,
) -> list[ModelCredentialFieldResponse]:
    _ = user
    return get_model_credential_form(provider)


@router.get("/workspaces/{workspace_id}/models", response_model=list[RegisteredModelResponse])
async def list_workspace_models(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[RegisteredModelResponse]:
    return await list_registered_models(db, context.workspace.id)


@router.post(
    "/workspaces/{workspace_id}/models",
    response_model=RegisteredModelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_model(
    payload: RegisteredModelCreateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RegisteredModelResponse:
    return await create_registered_model(db, context.workspace.id, payload, context.user, settings)


@router.get("/workspaces/{workspace_id}/models/{model_id}", response_model=RegisteredModelResponse)
async def get_workspace_model(
    model_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RegisteredModelResponse:
    model = await get_registered_model(db, context.workspace.id, model_id)
    return model_to_response(model)


@router.patch("/workspaces/{workspace_id}/models/{model_id}", response_model=RegisteredModelResponse)
async def patch_workspace_model(
    model_id: str,
    payload: RegisteredModelUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RegisteredModelResponse:
    model = await get_registered_model(db, context.workspace.id, model_id)
    return await update_registered_model(db, model, payload, context.user, settings)


@router.delete("/workspaces/{workspace_id}/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_model(
    model_id: str,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    model = await get_registered_model(db, context.workspace.id, model_id)
    await delete_registered_model(db, model, context.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
