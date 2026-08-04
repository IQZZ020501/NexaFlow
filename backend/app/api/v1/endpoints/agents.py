import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    WorkspaceContext,
    get_agent_orchestrator,
    get_settings,
    get_workspace_context_from_path,
)
from app.application.agents import (
    create_agent_run,
    get_agent_run,
    list_agent_runs,
    prepare_agent_run,
    prepare_agent_run_resume,
    run_to_response,
    stream_agent_run,
    stream_agent_run_resume,
)
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.schemas.agent import (
    AgentCreateRequest,
    AgentResponse,
    AgentRunCreateRequest,
    AgentRunResumeRequest,
    AgentRunResponse,
    AgentUpdateRequest,
)
from app.shareddomain.agents.runner import AgentOrchestrator
from app.shareddomain.agents.services import (
    create_agent,
    delete_agent,
    get_agent,
    get_agent_response,
    list_agents,
    update_agent,
)

logger = logging.getLogger(__name__)

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
    orchestrator: Annotated[AgentOrchestrator, Depends(get_agent_orchestrator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    agent = await get_agent(db, context.workspace.id, agent_id)
    run_ids = await delete_agent(db, agent, context.user, context.membership_role)
    for run_id in run_ids:
        try:
            await orchestrator.delete_run(run_id)
        except Exception:
            logger.exception("Failed to delete Agent checkpoint for run %s", run_id)
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


@router.get("/{agent_id}/runs/{run_id}", response_model=AgentRunResponse)
async def get_workspace_agent_run(
    agent_id: str,
    run_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRunResponse:
    return run_to_response(
        await get_agent_run(
            db,
            context.workspace.id,
            agent_id,
            run_id,
            context.user,
        )
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
    orchestrator: Annotated[AgentOrchestrator, Depends(get_agent_orchestrator)],
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
        orchestrator,
    )


@router.post("/{agent_id}/runs/stream", response_class=StreamingResponse)
async def stream_workspace_agent_run(
    agent_id: str,
    payload: AgentRunCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    orchestrator: Annotated[AgentOrchestrator, Depends(get_agent_orchestrator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    run, model = await prepare_agent_run(
        db,
        context.workspace.id,
        agent_id,
        payload.goal,
        context.user,
        context.membership_role,
    )

    async def encode_events() -> AsyncIterator[bytes]:
        async for event in stream_agent_run(
            db,
            run,
            model,
            context.user,
            context.membership_role,
            settings,
            orchestrator,
        ):
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode()

    return StreamingResponse(
        encode_events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{agent_id}/runs/{run_id}/resume/stream", response_class=StreamingResponse)
async def resume_workspace_agent_run(
    agent_id: str,
    run_id: str,
    payload: AgentRunResumeRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    orchestrator: Annotated[AgentOrchestrator, Depends(get_agent_orchestrator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    run, model, decision, recover = await prepare_agent_run_resume(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        payload.decision,
        context.user,
    )

    async def encode_events() -> AsyncIterator[bytes]:
        async for event in stream_agent_run_resume(
            db,
            run,
            model,
            context.user,
            context.membership_role,
            settings,
            orchestrator,
            decision=decision,
            recover=recover,
        ):
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode()

    return StreamingResponse(
        encode_events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
