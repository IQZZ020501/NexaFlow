from dataclasses import fields
from datetime import datetime
import hashlib
import json
from typing import Any

from sqlalchemy import and_, case, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.platform.models import ResourcePermission as ResourcePermissionORM
from app.entities.agents import Agent as AgentEntity
from app.entities.agents import AgentApiCredential as AgentApiCredentialEntity
from app.entities.agents import (
    AgentPublicationVersion as AgentPublicationVersionEntity,
)
from app.entities.runs import AgentRun as AgentRunEntity
from app.entities.runs import AgentRunEvent as AgentRunEventEntity
from app.entities.agents import AgentToolCall as AgentToolCallEntity
from app.entities.tools import ToolInvocation as ToolInvocationEntity
from app.entities.defaults import utc_now
from app.infra.db.mapping import (
    refresh_entity,
    save,
    to_entity,
    to_orm,
)
from app.domain.agents.models import (
    AGENT_RUN_ACTIVE_STATUSES,
    AGENT_RUN_AWAITING_APPROVAL_STATUS,
    AGENT_RUN_AWAITING_APPROVAL_STATUSES,
    AGENT_RUN_AWAITING_CHILD_STATUS,
    AGENT_RUN_AWAITING_CHILD_STATUSES,
    AGENT_RUN_AWAITING_INPUT_STATUS,
    AGENT_RUN_AWAITING_INPUT_STATUSES,
    AGENT_RUN_FAILED_STATUS,
    AGENT_RUN_LEGACY_CLAIMABLE_STATUSES,
    AGENT_RUN_QUEUED_STATUS,
    AGENT_RUN_RUNNING_STATUS,
    AGENT_RUN_RUNNING_STATUSES,
    AGENT_RUN_SUCCEEDED_STATUS,
    AGENT_RUN_CANCELLED_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_CHILD_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS,
    AGENT_RUN_UNIFIED_CLAIMABLE_STATUSES,
    AGENT_RUN_UNIFIED_QUEUED_STATUS,
    AGENT_RUN_UNIFIED_RUNNING_STATUS,
    agent_run_storage_statuses,
    Agent,
    AgentApiCredential,
    AgentKnowledgeBase,
    AgentMcpTool,
    AgentPublicationVersion,
    AgentRun,
    AgentRunEvent,
    AgentRunSnapshot,
    AgentRunState,
)
from app.domain.tools.models import ToolInvocation
from app.domain.workflows.models import WorkflowNodeExecution


from app.infra.db.repositories.runs.runs import _with_answer_ready_timestamp
async def append_agent_run_event(
    db: AsyncSession,
    workspace_id: str,
    run_id: str,
    event: dict,
) -> AgentRunEventEntity:
    created_at = utc_now()
    row = AgentRunEvent(
        workspace_id=workspace_id,
        run_id=run_id,
        event=_with_answer_ready_timestamp(event, created_at),
        created_at=created_at,
    )
    db.add(row)
    await db.flush()
    return to_entity(AgentRunEventEntity, row)

async def append_owned_agent_run_event(
    db: AsyncSession,
    workspace_id: str,
    run_id: str,
    worker_task_id: str,
    event: dict,
) -> AgentRunEventEntity | None:
    """Append an event only while the worker still owns the run lease."""
    run = await db.scalar(
        select(AgentRunState)
        .where(
            AgentRunState.workspace_id == workspace_id,
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRunState.worker_task_id == worker_task_id,
        )
        .with_for_update()
    )
    if run is None:
        return None
    return await append_agent_run_event(db, workspace_id, run_id, event)

async def list_agent_run_events(
    db: AsyncSession,
    run_id: str,
    after: int = 0,
    limit: int = 200,
) -> list[AgentRunEventEntity]:
    rows = await db.scalars(
        select(AgentRunEvent)
        .where(AgentRunEvent.run_id == run_id, AgentRunEvent.id > after)
        .order_by(AgentRunEvent.id)
        .limit(limit)
    )
    return [
        AgentRunEventEntity(
            id=row.id,
            workspace_id=row.workspace_id,
            run_id=row.run_id,
            event=_with_answer_ready_timestamp(row.event, row.created_at),
            created_at=row.created_at,
        )
        for row in rows.all()
    ]

