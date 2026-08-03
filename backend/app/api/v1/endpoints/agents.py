from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_settings, get_workspace_context_from_path
from app.application.agents import create_agent_run, list_agent_runs
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.schemas.agent import (
    AgentCreateRequest,
    AgentResponse,
    AgentRunCreateRequest,
    AgentRunResponse,
    AgentUpdateRequest,
)
from app.shareddomain.agents.services import (
    create_agent,
    delete_agent,
    get_agent,
    get_agent_response,
    list_agents,
    update_agent,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/agents",
    tags=["agents"],
)


@router.get("", response_model=list[AgentResponse])
async def list_workspace_agents(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AgentResponse]:
    return await list_agents(
        db,
        context.workspace.id,
        context.user,
        context.membership_role,
    )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_agent(
    payload: AgentCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentResponse:
    return await create_agent(
        db,
        context.workspace.id,
        payload,
        context.user,
        context.membership_role,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_workspace_agent(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentResponse:
    agent = await get_agent(db, context.workspace.id, agent_id)
    return await get_agent_response(
        db,
        agent,
        context.user,
        context.membership_role,
    )


@router.patch("/{agent_id}", response_model=AgentResponse)
async def patch_workspace_agent(
    agent_id: str,
    payload: AgentUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentResponse:
    agent = await get_agent(db, context.workspace.id, agent_id)
    return await update_agent(
        db,
        agent,
        payload,
        context.user,
        context.membership_role,
    )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_agent(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    agent = await get_agent(db, context.workspace.id, agent_id)
    await delete_agent(db, agent, context.user, context.membership_role)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{agent_id}/runs", response_model=list[AgentRunResponse])
async def list_workspace_agent_runs(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AgentRunResponse]:
    return await list_agent_runs(
        db,
        context.workspace.id,
        agent_id,
        context.user,
    )


@router.post(
    "/{agent_id}/runs",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_agent_run(
    agent_id: str,
    payload: AgentRunCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRunResponse:
    return await create_agent_run(
        db,
        context.workspace.id,
        agent_id,
        payload.goal,
        context.user,
        context.membership_role,
        settings,
    )
