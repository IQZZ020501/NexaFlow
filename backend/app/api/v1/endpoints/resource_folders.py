from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    WorkspaceContext,
    get_workspace_context_from_path,
    require_workspace_path_role,
)
from app.application.resource_folders import (
    create_resource_folder,
    delete_resource_folder,
    list_resource_folders,
    move_resource,
    move_resources,
    update_resource_folder,
)
from app.infrastructure.session import get_db
from app.schemas.resource_folder import (
    ResourceFolderBatchMoveRequest,
    ResourceFolderCreateRequest,
    ResourceFolderMoveRequest,
    ResourceFolderResponse,
    ResourceFolderType,
    ResourceFolderUpdateRequest,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/resource-folders",
    tags=["resource-folders"],
)


@router.get("", response_model=list[ResourceFolderResponse])
async def list_workspace_resource_folders(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    resource_type: Annotated[ResourceFolderType, Query()],
) -> list[ResourceFolderResponse]:
    return await list_resource_folders(db, context.workspace.id, resource_type)


@router.post("", response_model=ResourceFolderResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_resource_folder(
    payload: ResourceFolderCreateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResourceFolderResponse:
    return await create_resource_folder(db, context.workspace.id, payload, context.user)


@router.patch("/{folder_id}", response_model=ResourceFolderResponse)
async def update_workspace_resource_folder(
    folder_id: str,
    payload: ResourceFolderUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResourceFolderResponse:
    return await update_resource_folder(db, context.workspace.id, folder_id, payload)


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_resource_folder(
    folder_id: str,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await delete_resource_folder(db, context.workspace.id, folder_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/resources/move", status_code=status.HTTP_204_NO_CONTENT)
async def move_workspace_resource(
    payload: ResourceFolderMoveRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await move_resource(
        db,
        context.workspace.id,
        payload,
        context.user,
        context.membership_role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/resources/move-batch", status_code=status.HTTP_204_NO_CONTENT)
async def move_workspace_resources(
    payload: ResourceFolderBatchMoveRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await move_resources(
        db,
        context.workspace.id,
        payload,
        context.user,
        context.membership_role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
