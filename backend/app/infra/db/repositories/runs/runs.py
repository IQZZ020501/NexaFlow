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



_RUN_CORE_FIELDS = (
    "id",
    "workspace_id",
    "agent_id",
    "requested_by_user_id",
    "execution_user_id",
    "access_source",
    "consumer_id",
    "conversation_id",
    "root_run_id",
    "parent_run_id",
    "parent_node_id",
    "regenerated_from_run_id",
    "depth",
    "goal",
    "attachment_context",
    "feedback",
    "feedback_updated_at",
    "trace_id",
    "created_at",
)
_RUN_CORE_MUTABLE_FIELDS = (
    "goal",
    "attachment_context",
    "feedback",
    "feedback_updated_at",
    "trace_id",
)
_RUN_STATE_FIELDS = (
    "status",
    "attempts",
    "max_attempts",
    "worker_task_id",
    "lease_expires_at",
    "execution_deadline_at",
    "checkpoint",
    "checkpoint_phase",
    "grounding_status",
    "grounding_meta",
    "plan",
    "result",
    "context_summary",
    "model_usage",
    "last_error",
    "planned_at",
    "started_at",
    "finished_at",
    "updated_at",
)
_RUN_SNAPSHOT_FIELDS = (
    "snapshot_schema_version",
    "configuration_source",
    "agent_publication_version_id",
    "instructions",
    "knowledge_base_ids",
    "mcp_tools",
    "application_snapshot",
    "application_snapshot_hash",
    "tool_snapshots",
    "model_id",
    "model_name",
    "max_runtime_seconds",
    "max_turns",
    "max_tool_calls",
    "max_model_tokens",
    "model_runtime_snapshot",
    "knowledge_resource_snapshot",
)
def _entity_values(entity: Any, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(entity, name) for name in names}

def _run_query():
    return (
        select(AgentRun, AgentRunState, AgentRunSnapshot)
        .join(AgentRunState, AgentRunState.run_id == AgentRun.id)
        .join(AgentRunSnapshot, AgentRunSnapshot.run_id == AgentRun.id)
    )

def _to_agent_run_entity(
    run: AgentRun,
    state: AgentRunState,
    snapshot: AgentRunSnapshot,
    *,
    events: list[dict[str, Any]] | None = None,
) -> AgentRunEntity:
    sources = (run, state, snapshot)
    values: dict[str, Any] = {}
    for field in fields(AgentRunEntity):
        if field.name == "events":
            values[field.name] = events or []
            continue
        for source in sources:
            if hasattr(source, field.name):
                values[field.name] = getattr(source, field.name)
                break
    return AgentRunEntity(**values)

def _project_process_events(stored_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for stored in stored_events:
        if stored.get("type") != "process" or not isinstance(stored.get("event"), dict):
            continue
        event = stored["event"]
        call_id = event.get("call_id")
        for index, current in enumerate(projected):
            same_event = (
                current.get("call_id") == call_id
                if call_id
                else current.get("type") == event.get("type")
                and current.get("turn") == event.get("turn")
                and current.get("tool_name") == event.get("tool_name")
            )
            if same_event:
                projected[index] = event
                break
        else:
            projected.append(event)
    return [event for event in projected if event.get("status") != "running"]

def _with_answer_ready_timestamp(
    event: dict[str, Any], created_at: datetime
) -> dict[str, Any]:
    process_event = event.get("event")
    if (
        event.get("type") != "process"
        or not isinstance(process_event, dict)
        or process_event.get("summary") != "agent.answer_ready"
        or process_event.get("created_at")
    ):
        return event
    return {
        **event,
        "event": {**process_event, "created_at": created_at.isoformat()},
    }

async def _run_event_projections(
    db: AsyncSession,
    run_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not run_ids:
        return {}
    rows = await db.execute(
        select(AgentRunEvent.run_id, AgentRunEvent.event, AgentRunEvent.created_at)
        .where(AgentRunEvent.run_id.in_(run_ids))
        .order_by(AgentRunEvent.id)
    )
    stored: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
    for run_id, event, created_at in rows.all():
        stored.setdefault(run_id, []).append(
            _with_answer_ready_timestamp(event, created_at)
        )
    return {
        run_id: _project_process_events(events)
        for run_id, events in stored.items()
    }

async def _to_agent_run_entities(
    db: AsyncSession,
    rows: list[tuple[AgentRun, AgentRunState, AgentRunSnapshot]],
) -> list[AgentRunEntity]:
    projections = await _run_event_projections(db, [row[0].id for row in rows])
    return [
        _to_agent_run_entity(run, state, snapshot, events=projections.get(run.id))
        for run, state, snapshot in rows
    ]

def _worker_generation(configuration_source: str) -> str:
    return "unified" if configuration_source in {"draft", "published"} else "legacy"

async def _load_run_rows(
    db: AsyncSession,
    run_id: str,
) -> tuple[AgentRun, AgentRunState, AgentRunSnapshot] | None:
    row = (
        await db.execute(_run_query().where(AgentRun.id == run_id))
    ).first()
    return tuple(row) if row is not None else None

async def get_active_agent_run(
    db: AsyncSession,
    agent_id: str,
    access_source: str,
    consumer_id: str,
    conversation_id: str,
) -> AgentRunEntity | None:
    row = (
        await db.execute(
            _run_query()
        .where(
            AgentRun.agent_id == agent_id,
            AgentRun.access_source == access_source,
            AgentRun.consumer_id == consumer_id,
            AgentRun.conversation_id == conversation_id,
            AgentRunState.status.in_(AGENT_RUN_ACTIVE_STATUSES),
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
        )
    ).first()
    if row is None:
        return None
    return (await _to_agent_run_entities(db, [tuple(row)]))[0]

async def get_agent_run_by_id(
    db: AsyncSession,
    run_id: str,
) -> AgentRunEntity | None:
    row = await _load_run_rows(db, run_id)
    if row is None:
        return None
    projections = await _run_event_projections(db, [run_id])
    return _to_agent_run_entity(*row, events=projections.get(run_id))

async def create_agent_run(db: AsyncSession, entity: AgentRunEntity) -> AgentRunEntity:
    run = AgentRun(**_entity_values(entity, _RUN_CORE_FIELDS))
    state = AgentRunState(
        run_id=entity.id,
        workspace_id=entity.workspace_id,
        agent_id=entity.agent_id,
        access_source=entity.access_source,
        consumer_id=entity.consumer_id,
        conversation_id=entity.conversation_id,
        worker_generation=_worker_generation(entity.configuration_source),
        state_version=1,
        **_entity_values(entity, _RUN_STATE_FIELDS),
    )
    snapshot = AgentRunSnapshot(
        run_id=entity.id,
        workspace_id=entity.workspace_id,
        agent_id=entity.agent_id,
        created_at=entity.created_at,
        **_entity_values(entity, _RUN_SNAPSHOT_FIELDS),
    )
    db.add_all((run, state, snapshot))
    for event in entity.events:
        db.add(
            AgentRunEvent(
                workspace_id=entity.workspace_id,
                run_id=entity.id,
                event={"type": "process", "event": event},
            )
        )
    await db.flush()
    return _to_agent_run_entity(run, state, snapshot, events=list(entity.events))

async def save_agent_run(db: AsyncSession, entity: AgentRunEntity) -> AgentRunEntity:
    rows = await _load_run_rows(db, entity.id)
    if rows is None:
        return await create_agent_run(db, entity)
    run, state, snapshot = rows
    for name in _RUN_CORE_MUTABLE_FIELDS:
        setattr(run, name, getattr(entity, name))
    for name in _RUN_STATE_FIELDS:
        setattr(state, name, getattr(entity, name))
    state.state_version += 1
    if entity.events:
        current = (await _run_event_projections(db, [entity.id])).get(entity.id, [])
        if current != entity.events:
            for event in entity.events:
                db.add(
                    AgentRunEvent(
                        workspace_id=entity.workspace_id,
                        run_id=entity.id,
                        event={"type": "process", "event": event},
                    )
                )
    await db.flush()
    return _to_agent_run_entity(run, state, snapshot, events=list(entity.events))

async def refresh_agent_run(db: AsyncSession, entity: AgentRunEntity) -> AgentRunEntity:
    current = await get_agent_run_by_id(db, entity.id)
    if current is None:
        raise RuntimeError("Agent run no longer exists.")
    return current

async def finalize_agent_run(
    db: AsyncSession,
    run_id: str,
    worker_task_id: str,
    *,
    status: str,
    result: str,
    events: list[dict],
    last_error: str | None,
    finished_at: datetime,
    model_usage: dict | None = None,
    grounding_status: str | None = None,
    grounding_meta: dict | None = None,
) -> bool:
    del events
    values = {
        "status": status,
        "result": result,
        "state_version": AgentRunState.state_version + 1,
        "last_error": last_error,
        "finished_at": finished_at,
        "worker_task_id": None,
        "lease_expires_at": None,
        "updated_at": finished_at,
    }
    if model_usage is not None:
        values["model_usage"] = model_usage
    if grounding_status is not None:
        values["grounding_status"] = grounding_status
    if grounding_meta is not None:
        values["grounding_meta"] = grounding_meta
    updated = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRunState.worker_task_id == worker_task_id,
        )
        .values(**values)
    )
    return bool(updated.rowcount)

async def pause_agent_run(
    db: AsyncSession,
    run_id: str,
    worker_task_id: str,
    reason: str,
) -> bool:
    updated = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRunState.worker_task_id == worker_task_id,
        )
        .values(
            status=case(
                (
                    AgentRunState.worker_generation == "unified",
                    AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS,
                ),
                else_=AGENT_RUN_AWAITING_APPROVAL_STATUS,
            ),
            attempts=case(
                (AgentRunState.attempts > 0, AgentRunState.attempts - 1),
                else_=0,
            ),
            state_version=AgentRunState.state_version + 1,
            last_error=reason,
            worker_task_id=None,
            lease_expires_at=None,
            updated_at=func.now(),
        )
    )
    return bool(updated.rowcount)

async def pause_agent_run_for_input(
    db: AsyncSession,
    run_id: str,
    worker_task_id: str,
) -> bool:
    updated = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRunState.worker_task_id == worker_task_id,
        )
        .values(
            status=case(
                (
                    AgentRunState.worker_generation == "unified",
                    AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS,
                ),
                else_=AGENT_RUN_AWAITING_INPUT_STATUS,
            ),
            attempts=case(
                (AgentRunState.attempts > 0, AgentRunState.attempts - 1),
                else_=0,
            ),
            state_version=AgentRunState.state_version + 1,
            last_error=None,
            worker_task_id=None,
            lease_expires_at=None,
            updated_at=func.now(),
        )
    )
    return bool(updated.rowcount)

async def pause_agent_run_for_child(
    db: AsyncSession,
    run_id: str,
    worker_task_id: str,
) -> bool:
    updated = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRunState.worker_task_id == worker_task_id,
        )
        .values(
            status=case(
                (
                    AgentRunState.worker_generation == "unified",
                    AGENT_RUN_UNIFIED_AWAITING_CHILD_STATUS,
                ),
                else_=AGENT_RUN_AWAITING_CHILD_STATUS,
            ),
            attempts=case(
                (AgentRunState.attempts > 0, AgentRunState.attempts - 1),
                else_=0,
            ),
            state_version=AgentRunState.state_version + 1,
            last_error=None,
            worker_task_id=None,
            lease_expires_at=None,
            updated_at=func.now(),
        )
    )
    return bool(updated.rowcount)
