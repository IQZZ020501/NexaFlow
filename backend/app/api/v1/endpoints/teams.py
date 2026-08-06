from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.session import get_db
from app.api.deps import (
    WorkspaceContext,
    get_workspace_context_from_path,
    require_workspace_path_role,
)
from app.application.teams import (
    create_team,
    delete_team_permanently,
    get_team,
    list_teams,
    update_team,
)
from app.schemas.team import TeamCreateRequest, TeamResponse, TeamUpdateRequest

router = APIRouter(prefix="/workspaces/{workspace_id}/teams", tags=["teams"])


@router.get("", response_model=list[TeamResponse])
async def list_workspace_teams(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamResponse]:
    return await list_teams(db, context.workspace.id, limit, offset)


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_team(
    payload: TeamCreateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TeamResponse:
    return await create_team(db, context.workspace.id, payload, context.user)


@router.patch("/{team_id}", response_model=TeamResponse)
async def patch_team(
    team_id: str,
    payload: TeamUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TeamResponse:
    team = await get_team(db, context.workspace.id, team_id)
    return await update_team(db, team, payload, context.user)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: str,
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    team = await get_team(db, context.workspace.id, team_id)
    await delete_team_permanently(db, team, context.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
