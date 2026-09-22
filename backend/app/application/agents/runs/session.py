"""Authorized durable input for an existing Agent session execution."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agents.runs.service import get_agent_run_entity
from app.application.agents.tools.builder import session_inputs_to_response
from app.entities.identity import User
from app.entities.runs import AgentRun
from app.infra.db.repositories.runs.session_inputs import enqueue_session_input
from app.schemas.agents.contracts import (
    AgentSessionInputRequest,
    AgentSessionInputResponse,
)


async def append_session_input(
    db: AsyncSession, run: AgentRun, payload: AgentSessionInputRequest
) -> AgentSessionInputResponse:
    try:
        stored = await enqueue_session_input(
            db,
            run.workspace_id,
            run.id,
            payload.input_id,
            payload.mode,
            payload.content.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    assert stored.id is not None
    consumed_input = next(
        (
            item
            for item in session_inputs_to_response(run)
            if item["sequence"] == stored.id
        ),
        {},
    )
    return AgentSessionInputResponse(
        sequence=stored.id,
        run_id=run.id,
        input_id=payload.input_id,
        mode=payload.mode,
        content=payload.content.strip(),
        status=(
            "applied"
            if stored.id
            in (run.checkpoint or {}).get("harness", {}).get("input_ids", [])
            else "queued"
        ),
        previous_answer=consumed_input.get("previous_answer"),
        previous_answer_turn=consumed_input.get("previous_answer_turn"),
    )


async def send_agent_session_input(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    run_id: str,
    payload: AgentSessionInputRequest,
    actor: User,
    workspace_role: str | None,
) -> AgentSessionInputResponse:
    run = await get_agent_run_entity(
        db, workspace_id, agent_id, run_id, actor, workspace_role
    )
    return await append_session_input(db, run, payload)
