"""Append-only session input queue, serialized with Run finalization."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agents.models import (
    AGENT_RUN_ACTIVE_STATUSES,
    AgentRunEvent,
    AgentRunState,
)
from app.entities.defaults import utc_now
from app.entities.runs import AgentRunEvent as AgentRunEventEntity
from app.infra.db.mapping import to_entity

MAX_SESSION_INPUTS = 32


async def list_session_inputs(
    db: AsyncSession, run_id: str
) -> list[AgentRunEventEntity]:
    rows = await db.scalars(
        select(AgentRunEvent)
        .where(
            AgentRunEvent.run_id == run_id,
            AgentRunEvent.event["type"].as_string() == "session_input",
        )
        .order_by(AgentRunEvent.id)
        .limit(MAX_SESSION_INPUTS)
    )
    return [to_entity(AgentRunEventEntity, row) for row in rows]


async def enqueue_session_input(
    db: AsyncSession,
    workspace_id: str,
    run_id: str,
    input_id: str,
    content: str,
) -> AgentRunEventEntity:
    state = await db.scalar(
        select(AgentRunState)
        .where(
            AgentRunState.workspace_id == workspace_id, AgentRunState.run_id == run_id
        )
        .with_for_update()
    )
    if state is None:
        raise ValueError("Agent run not found.")
    inputs = await list_session_inputs(db, run_id)
    for previous in inputs:
        if previous.event["input_id"] == input_id:
            if previous.event["content"] != content:
                raise ValueError(
                    "Session input ID was already used for different content."
                )
            return previous
    if state.status not in AGENT_RUN_ACTIVE_STATUSES:
        raise ValueError("Agent run is already finished. Send a new session prompt.")
    if len(inputs) >= MAX_SESSION_INPUTS:
        raise ValueError("Agent session input queue limit reached.")
    row = AgentRunEvent(
        workspace_id=workspace_id,
        run_id=run_id,
        event={
            "type": "session_input",
            "input_id": input_id,
            "mode": "follow_up",
            "content": content,
        },
        created_at=utc_now(),
    )
    db.add(row)
    await db.flush()
    return to_entity(AgentRunEventEntity, row)


async def pending_session_inputs(
    db: AsyncSession, run_id: str, consumed: list[int]
) -> list[dict]:
    return [
        {"id": item.id, **item.event, "mode": "follow_up"}
        for item in await list_session_inputs(db, run_id)
        if item.id not in consumed
    ]
