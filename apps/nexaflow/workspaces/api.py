from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.db.session import get_db
from nexaflow.identity.deps import require_global_admin, require_password_changed
from nexaflow.identity.models import User
from nexaflow.workspaces.models import WorkspaceMembership
from nexaflow.workspaces.schemas import (
    WorkspaceCreateRequest,
    WorkspaceCreateResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)
from nexaflow.workspaces.services import (
    create_workspace,
    delete_workspace_permanently,
    get_workspace_for_user,
    list_workspaces,
    update_workspace,
    workspace_to_response,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_current_workspaces(
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkspaceResponse]:
    return await list_workspaces(db, user)


@router.post("", response_model=WorkspaceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_new_workspace(
    payload: WorkspaceCreateRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceCreateResponse:
    return await create_workspace(db, payload, actor)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    return workspace_to_response(await get_workspace_for_user(db, workspace_id, user))


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def patch_workspace(
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    workspace = await get_workspace_for_user(db, workspace_id, user)
    if not user.is_global_admin:
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == user.id,
            )
        )
        if membership is None or membership.role not in {"owner", "admin"}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace admin required.")
    return await update_workspace(db, workspace, payload, user)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    workspace = await get_workspace_for_user(db, workspace_id, actor)
    await delete_workspace_permanently(db, workspace, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
