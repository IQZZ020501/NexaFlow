from dataclasses import fields
from datetime import datetime
import hashlib
import json
from typing import Any

from sqlalchemy import and_, case, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.shareddomain.platform.models import ResourcePermission as ResourcePermissionORM
from app.entities.agents import Agent as AgentEntity
from app.entities.agents import AgentApiCredential as AgentApiCredentialEntity
from app.entities.agents import (
    AgentPublicationVersion as AgentPublicationVersionEntity,
)
from app.entities.agents import AgentRun as AgentRunEntity
from app.entities.agents import AgentRunEvent as AgentRunEventEntity
from app.entities.agents import AgentToolCall as AgentToolCallEntity
from app.entities.tools import ToolInvocation as ToolInvocationEntity
from app.infrastructure.repositories.mapping import (
    refresh_entity,
    save,
    to_entity,
    to_orm,
)
from app.shareddomain.agents.models import (
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
from app.shareddomain.tools.models import ToolInvocation
from app.shareddomain.workflows.models import WorkflowNodeExecution

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
    "knowledge_query_mode",
    "mcp_tools",
    "application_snapshot",
    "application_snapshot_hash",
    "tool_snapshots",
    "model_id",
    "model_name",
)
_INTERNAL_TOOL_LEDGER = "agent_internal_v1"


def _entity_values(entity: Any, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(entity, name) for name in names}


def _run_query():
    return (
        select(AgentRun, AgentRunState, AgentRunSnapshot)
        .join(AgentRunState, AgentRunState.run_id == AgentRun.id)
        .join(AgentRunSnapshot, AgentRunSnapshot.run_id == AgentRun.id)
    )


def _memory_run_query():
    return select(
        AgentRun.id,
        AgentRun.workspace_id,
        AgentRun.agent_id,
        AgentRun.access_source,
        AgentRun.consumer_id,
        AgentRun.conversation_id,
        AgentRun.goal,
        AgentRun.attachment_context,
        AgentRun.created_at,
        AgentRunState.status,
        AgentRunState.result,
        AgentRunState.context_summary,
    ).join(AgentRunState, AgentRunState.run_id == AgentRun.id)


def _to_memory_run_entity(row: Any) -> AgentRunEntity:
    return AgentRunEntity(**dict(row))


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


async def _run_event_projections(
    db: AsyncSession,
    run_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not run_ids:
        return {}
    rows = await db.execute(
        select(AgentRunEvent.run_id, AgentRunEvent.event)
        .where(AgentRunEvent.run_id.in_(run_ids))
        .order_by(AgentRunEvent.id)
    )
    stored: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
    for run_id, event in rows.all():
        stored.setdefault(run_id, []).append(event)
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


async def list_agents(
    db: AsyncSession,
    workspace_id: str,
    actor_id: str,
    resource_type: str,
    include_all: bool,
    limit: int | None = None,
    offset: int = 0,
) -> list[AgentEntity]:
    grant = ResourcePermissionORM
    statement = (
        select(Agent)
        .outerjoin(
            grant,
            (
                (grant.workspace_id == Agent.workspace_id)
                & (grant.resource_type == resource_type)
                & (grant.resource_id == Agent.id)
                & (grant.user_id == actor_id)
            ),
        )
        .where(Agent.workspace_id == workspace_id)
    )
    if not include_all:
        statement = statement.where(
            or_(
                Agent.created_by_user_id == actor_id,
                grant.id.is_not(None),
            )
        )
    result = await db.scalars(
        statement
        .order_by(Agent.created_at.desc(), Agent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(AgentEntity, row) for row in result.all()]


async def get_agent_by_id(db: AsyncSession, agent_id: str) -> AgentEntity | None:
    row = await db.get(Agent, agent_id)
    return to_entity(AgentEntity, row) if row is not None else None


async def lock_agent(db: AsyncSession, agent_id: str) -> AgentEntity | None:
    row = await db.scalar(
        select(Agent).where(Agent.id == agent_id).with_for_update()
    )
    return to_entity(AgentEntity, row) if row is not None else None


async def create_agent(db: AsyncSession, entity: AgentEntity) -> AgentEntity:
    orm = await save(db, Agent, entity)
    return to_entity(AgentEntity, orm)


async def save_agent(db: AsyncSession, entity: AgentEntity) -> AgentEntity:
    orm = await save(db, Agent, entity)
    return to_entity(AgentEntity, orm)


async def refresh_agent(db: AsyncSession, entity: AgentEntity) -> AgentEntity:
    return await refresh_entity(db, Agent, AgentEntity, entity)


async def create_agent_publication_version(
    db: AsyncSession,
    entity: AgentPublicationVersionEntity,
) -> AgentPublicationVersionEntity:
    if await db.get(AgentPublicationVersion, entity.id) is not None:
        raise ValueError("Agent publication versions are immutable.")
    row = to_orm(AgentPublicationVersion, entity)
    db.add(row)
    await db.flush()
    return to_entity(AgentPublicationVersionEntity, row)


async def next_agent_publication_version_number(
    db: AsyncSession,
    agent_id: str,
) -> int:
    value = await db.scalar(
        select(func.max(AgentPublicationVersion.version_number)).where(
            AgentPublicationVersion.agent_id == agent_id
        )
    )
    return int(value or 0) + 1


async def get_agent_publication_version(
    db: AsyncSession,
    workspace_id: str,
    version_id: str,
) -> AgentPublicationVersionEntity | None:
    row = await db.scalar(
        select(AgentPublicationVersion).where(
            AgentPublicationVersion.workspace_id == workspace_id,
            AgentPublicationVersion.id == version_id,
        )
    )
    return (
        to_entity(AgentPublicationVersionEntity, row) if row is not None else None
    )


async def list_agent_publication_version_map(
    db: AsyncSession,
    workspace_id: str,
    version_ids: list[str],
) -> dict[str, AgentPublicationVersionEntity]:
    if not version_ids:
        return {}
    rows = await db.scalars(
        select(AgentPublicationVersion).where(
            AgentPublicationVersion.workspace_id == workspace_id,
            AgentPublicationVersion.id.in_(version_ids),
        )
    )
    versions = [to_entity(AgentPublicationVersionEntity, row) for row in rows.all()]
    return {version.id: version for version in versions}


async def has_agent_publication_audit_references(
    db: AsyncSession,
    user_id: str,
) -> bool:
    publisher_reference = await db.scalar(
        select(AgentPublicationVersion.id)
        .where(AgentPublicationVersion.published_by_user_id == user_id)
        .limit(1)
    )
    if publisher_reference is not None:
        return True
    # ponytail: user deletion is rare; use a portable scan until publication volume warrants JSON indexing.
    resources = await db.scalars(select(AgentPublicationVersion.resource_snapshot))
    for resource_snapshot in resources.all():
        tools = resource_snapshot.get("tools", [])
        if isinstance(tools, list) and any(
            isinstance(tool, dict) and tool.get("bound_by_user_id") == user_id
            for tool in tools
        ):
            return True
    run_snapshots = await db.scalars(select(AgentRunSnapshot.tool_snapshots))
    for tool_snapshots in run_snapshots.all():
        if isinstance(tool_snapshots, list) and any(
            isinstance(tool, dict) and tool.get("bound_by_user_id") == user_id
            for tool in tool_snapshots
        ):
            return True
    return False


async def list_agent_api_credentials(
    db: AsyncSession,
    agent_id: str,
) -> list[AgentApiCredentialEntity]:
    rows = await db.scalars(
        select(AgentApiCredential)
        .where(AgentApiCredential.agent_id == agent_id)
        .order_by(AgentApiCredential.created_at.desc(), AgentApiCredential.id.desc())
    )
    return [to_entity(AgentApiCredentialEntity, row) for row in rows.all()]


async def get_agent_api_credential_by_id(
    db: AsyncSession,
    credential_id: str,
) -> AgentApiCredentialEntity | None:
    row = await db.get(AgentApiCredential, credential_id)
    return to_entity(AgentApiCredentialEntity, row) if row is not None else None


async def list_agent_api_credentials_by_ids(
    db: AsyncSession,
    credential_ids: list[str],
) -> list[AgentApiCredentialEntity]:
    if not credential_ids:
        return []
    rows = await db.scalars(
        select(AgentApiCredential).where(AgentApiCredential.id.in_(credential_ids))
    )
    return [to_entity(AgentApiCredentialEntity, row) for row in rows.all()]


async def get_agent_api_credential_by_hash(
    db: AsyncSession,
    token_hash: str,
) -> AgentApiCredentialEntity | None:
    row = await db.scalar(
        select(AgentApiCredential).where(
            AgentApiCredential.token_hash == token_hash,
            AgentApiCredential.revoked_at.is_(None),
        )
    )
    return to_entity(AgentApiCredentialEntity, row) if row is not None else None


async def create_agent_api_credential(
    db: AsyncSession,
    entity: AgentApiCredentialEntity,
) -> AgentApiCredentialEntity:
    orm = await save(db, AgentApiCredential, entity)
    return to_entity(AgentApiCredentialEntity, orm)


async def mark_agent_api_credential_used(
    db: AsyncSession,
    credential_id: str,
    used_at: datetime,
) -> bool:
    result = await db.execute(
        update(AgentApiCredential)
        .where(
            AgentApiCredential.id == credential_id,
            AgentApiCredential.revoked_at.is_(None),
        )
        .values(last_used_at=used_at)
    )
    return bool(result.rowcount)


async def revoke_agent_api_credential(
    db: AsyncSession,
    credential_id: str,
    revoked_at: datetime,
) -> bool:
    result = await db.execute(
        update(AgentApiCredential)
        .where(
            AgentApiCredential.id == credential_id,
            AgentApiCredential.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at)
    )
    return bool(result.rowcount)


async def rotate_agent_api_credential(
    db: AsyncSession,
    credential_id: str,
    current_token_hash: str,
    token_hash: str,
    hint: str,
) -> bool:
    result = await db.execute(
        update(AgentApiCredential)
        .where(
            AgentApiCredential.id == credential_id,
            AgentApiCredential.token_hash == current_token_hash,
            AgentApiCredential.revoked_at.is_(None),
        )
        .values(token_hash=token_hash, hint=hint)
    )
    return bool(result.rowcount)


async def list_binding_map(
    db: AsyncSession,
    agent_ids: list[str],
) -> dict[str, list[str]]:
    bindings = {agent_id: [] for agent_id in agent_ids}
    if not agent_ids:
        return bindings
    rows = await db.execute(
        select(AgentKnowledgeBase.agent_id, AgentKnowledgeBase.knowledge_base_id)
        .where(AgentKnowledgeBase.agent_id.in_(agent_ids))
        .order_by(AgentKnowledgeBase.created_at)
    )
    for agent_id, knowledge_base_id in rows.all():
        bindings[agent_id].append(knowledge_base_id)
    return bindings


async def replace_bindings(
    db: AsyncSession,
    agent: AgentEntity,
    knowledge_base_ids: list[str],
) -> None:
    await db.execute(
        delete(AgentKnowledgeBase).where(AgentKnowledgeBase.agent_id == agent.id)
    )
    db.add_all(
        [
            AgentKnowledgeBase(
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                knowledge_base_id=knowledge_base_id,
            )
            for knowledge_base_id in knowledge_base_ids
        ]
    )


async def list_mcp_binding_map(
    db: AsyncSession,
    agent_ids: list[str],
) -> dict[str, list[dict[str, str]]]:
    bindings: dict[str, list[dict[str, str]]] = {
        agent_id: [] for agent_id in agent_ids
    }
    if not agent_ids:
        return bindings
    rows = await db.execute(
        select(
            AgentMcpTool.agent_id,
            AgentMcpTool.mcp_server_id,
            AgentMcpTool.tool_name,
        )
        .where(AgentMcpTool.agent_id.in_(agent_ids))
        .order_by(AgentMcpTool.created_at)
    )
    for agent_id, server_id, tool_name in rows.all():
        bindings[agent_id].append(
            {"server_id": server_id, "tool_name": tool_name}
        )
    return bindings


async def replace_mcp_bindings(
    db: AsyncSession,
    agent: AgentEntity,
    references: list[dict[str, str]],
) -> None:
    await db.execute(
        delete(AgentMcpTool).where(AgentMcpTool.agent_id == agent.id)
    )
    db.add_all(
        [
            AgentMcpTool(
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                mcp_server_id=reference["server_id"],
                tool_name=reference["tool_name"],
            )
            for reference in references
        ]
    )


async def list_agent_runs(
    db: AsyncSession,
    agent_id: str,
    access_source: str,
    consumer_id: str,
    limit: int | None = None,
    offset: int = 0,
    *,
    status: str | None = None,
    conversation_id: str | None = None,
    latest_versions_only: bool = False,
) -> list[AgentRunEntity]:
    """
    List runs for an agent and consumer, optionally filtered by status or conversation.
    
    Parameters:
    	access_source (str): The source through which the runs were accessed.
    	consumer_id (str): The identifier of the consumer associated with the runs.
        latest_versions_only (bool): Whether to exclude failed or cancelled regenerated runs and runs with a non-failed, non-cancelled successor.
    
    Returns:
    	list[AgentRunEntity]: Runs matching the specified filters, ordered from newest to oldest.
    """
    statement = (
        _run_query()
        .where(
            AgentRun.agent_id == agent_id,
            AgentRun.access_source == access_source,
            AgentRun.consumer_id == consumer_id,
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        statement = statement.where(
            AgentRunState.status.in_(agent_run_storage_statuses(status))
        )
    if conversation_id is not None:
        statement = statement.where(AgentRun.conversation_id == conversation_id)
    if latest_versions_only:
        successor = aliased(AgentRun)
        successor_state = aliased(AgentRunState)
        statement = statement.where(
            (
                AgentRun.regenerated_from_run_id.is_(None)
                | AgentRunState.status.notin_(
                    (AGENT_RUN_FAILED_STATUS, AGENT_RUN_CANCELLED_STATUS)
                )
            ),
            ~exists(
                select(successor.id)
                .join(successor_state, successor_state.run_id == successor.id)
                .where(
                    successor.regenerated_from_run_id == AgentRun.id,
                    successor_state.status.notin_(
                        (AGENT_RUN_FAILED_STATUS, AGENT_RUN_CANCELLED_STATUS)
                    ),
                )
            )
        )
    result = await db.execute(statement)
    return await _to_agent_run_entities(db, [tuple(row) for row in result.all()])


async def count_agent_runs(
    db: AsyncSession,
    agent_id: str,
    *,
    access_source: str | None = None,
    consumer_id: str | None = None,
    conversation_id: str | None = None,
    latest_versions_only: bool = False,
) -> int:
    """
    Count runs belonging to an agent, with optional access, consumer, conversation, and version filters.
    
    Parameters:
        latest_versions_only (bool): Whether to count only runs without a non-failed, non-cancelled regenerated successor.
    
    Returns:
        int: The number of matching runs.
    """
    statement = (
        select(func.count())
        .select_from(AgentRun)
        .join(AgentRunState, AgentRunState.run_id == AgentRun.id)
        .where(AgentRun.agent_id == agent_id)
    )
    if access_source is not None:
        statement = statement.where(AgentRun.access_source == access_source)
    if consumer_id is not None:
        statement = statement.where(AgentRun.consumer_id == consumer_id)
    if conversation_id is not None:
        statement = statement.where(AgentRun.conversation_id == conversation_id)
    if latest_versions_only:
        successor = aliased(AgentRun)
        successor_state = aliased(AgentRunState)
        statement = statement.where(
            (
                AgentRun.regenerated_from_run_id.is_(None)
                | AgentRunState.status.notin_(
                    (AGENT_RUN_FAILED_STATUS, AGENT_RUN_CANCELLED_STATUS)
                )
            ),
            ~exists(
                select(successor.id)
                .join(successor_state, successor_state.run_id == successor.id)
                .where(
                    successor.regenerated_from_run_id == AgentRun.id,
                    successor_state.status.notin_(
                        (AGENT_RUN_FAILED_STATUS, AGENT_RUN_CANCELLED_STATUS)
                    ),
                )
            )
        )
    return int(await db.scalar(statement) or 0)


async def list_agent_runs_for_management(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    limit: int,
    offset: int,
) -> list[AgentRunEntity]:
    rows = await db.execute(
        _run_query()
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.agent_id == agent_id,
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return await _to_agent_run_entities(db, [tuple(row) for row in rows.all()])


async def list_agent_consumer_stats(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    limit: int,
    offset: int,
) -> tuple[list[tuple], int]:
    grouped = (
        select(
            AgentRun.access_source.label("access_source"),
            AgentRun.consumer_id.label("consumer_id"),
            func.min(AgentRun.created_at).label("first_seen_at"),
            func.max(AgentRun.created_at).label("last_seen_at"),
            func.count(func.distinct(AgentRun.conversation_id)).label(
                "conversation_count"
            ),
            func.count().label("run_count"),
        )
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.agent_id == agent_id,
        )
        .group_by(AgentRun.access_source, AgentRun.consumer_id)
        .subquery()
    )
    total = int(
        await db.scalar(select(func.count()).select_from(grouped)) or 0
    )
    result = await db.execute(
        select(grouped)
        .order_by(grouped.c.last_seen_at.desc(), grouped.c.consumer_id)
        .limit(limit)
        .offset(offset)
    )
    return list(result.all()), total


async def list_agent_monitoring_rows(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    since: datetime,
) -> list[tuple]:
    result = await db.execute(
        select(
            AgentRun.created_at,
            AgentRun.access_source,
            AgentRun.consumer_id,
            AgentRun.conversation_id,
            AgentRunState.status,
            AgentRunState.model_usage,
        )
        .join(AgentRunState, AgentRunState.run_id == AgentRun.id)
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.agent_id == agent_id,
            AgentRun.created_at >= since,
        )
    )
    return list(result.all())


async def list_consumer_conversations(
    db: AsyncSession,
    agent_id: str,
    access_source: str,
    consumer_id: str,
) -> list[tuple]:
    """
    List conversations for a consumer, including their latest visible run and activity totals.
    
    Parameters:
        agent_id (str): Identifier of the agent.
        access_source (str): Source through which the consumer accesses the agent.
        consumer_id (str): Identifier of the consumer.
    
    Returns:
        list[tuple]: Rows containing the latest run ID, conversation ID, goal, status,
        result, run count, creation time, and last update time for each conversation.
    """
    scope = (
        AgentRun.agent_id == agent_id,
        AgentRun.access_source == access_source,
        AgentRun.consumer_id == consumer_id,
    )
    successor = aliased(AgentRun)
    successor_state = aliased(AgentRunState)
    visible = (
        (
            AgentRun.regenerated_from_run_id.is_(None)
            | AgentRunState.status.notin_(
                (AGENT_RUN_FAILED_STATUS, AGENT_RUN_CANCELLED_STATUS)
            )
        )
        & ~exists(
            select(successor.id)
            .join(successor_state, successor_state.run_id == successor.id)
            .where(
                successor.regenerated_from_run_id == AgentRun.id,
                successor_state.status.notin_(
                    (AGENT_RUN_FAILED_STATUS, AGENT_RUN_CANCELLED_STATUS)
                ),
            )
        )
    )
    aggregates = (
        select(
            AgentRun.conversation_id.label("conversation_id"),
            func.count().label("run_count"),
            func.min(AgentRun.created_at).label("created_at"),
            func.max(AgentRunState.updated_at).label("updated_at"),
        )
        .join(AgentRunState, AgentRunState.run_id == AgentRun.id)
        .where(*scope, visible)
        .group_by(AgentRun.conversation_id)
        .subquery()
    )
    ranked = (
        select(
            AgentRun.id.label("run_id"),
            AgentRun.conversation_id.label("conversation_id"),
            AgentRun.goal.label("goal"),
            AgentRunState.status.label("status"),
            AgentRunState.result.label("result"),
            func.row_number()
            .over(
                partition_by=AgentRun.conversation_id,
                order_by=(AgentRun.created_at.desc(), AgentRun.id.desc()),
            )
            .label("rank"),
        )
        .join(AgentRunState, AgentRunState.run_id == AgentRun.id)
        .where(*scope, visible)
        .subquery()
    )
    result = await db.execute(
        select(
            ranked.c.run_id,
            aggregates.c.conversation_id,
            ranked.c.goal,
            ranked.c.status,
            ranked.c.result,
            aggregates.c.run_count,
            aggregates.c.created_at,
            aggregates.c.updated_at,
        )
        .join(
            ranked,
            and_(
                ranked.c.conversation_id == aggregates.c.conversation_id,
                ranked.c.rank == 1,
            ),
        )
        .order_by(aggregates.c.updated_at.desc(), aggregates.c.conversation_id)
    )
    return list(result.all())


async def delete_consumer_conversation(
    db: AsyncSession,
    agent_id: str,
    access_source: str,
    consumer_id: str,
    conversation_id: str,
) -> tuple[bool, bool]:
    """Delete one consumer conversation and its persisted run graph.

    Returns ``(deleted, active)``. Active runs are left intact so a worker
    cannot continue writing into a conversation while it is being removed.
    """
    scope = (
        AgentRun.agent_id == agent_id,
        AgentRun.access_source == access_source,
        AgentRun.consumer_id == consumer_id,
        AgentRun.conversation_id == conversation_id,
    )
    exists = await db.scalar(select(AgentRun.id).where(*scope).limit(1))
    if exists is None:
        return False, False
    active = await db.scalar(
        select(AgentRun.id)
        .join(AgentRunState, AgentRunState.run_id == AgentRun.id)
        .where(*scope, AgentRunState.status.in_(AGENT_RUN_ACTIVE_STATUSES))
        .limit(1)
    )
    if active is not None:
        return False, True
    result = await db.execute(delete(AgentRun).where(*scope))
    return bool(result.rowcount), False


async def latest_agent_conversation_id(
    db: AsyncSession,
    agent_id: str,
    access_source: str,
    consumer_id: str,
) -> str | None:
    return await db.scalar(
        select(AgentRun.conversation_id)
        .where(
            AgentRun.agent_id == agent_id,
            AgentRun.access_source == access_source,
            AgentRun.consumer_id == consumer_id,
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )


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


async def list_conversation_memory_runs(
    db: AsyncSession,
    run: AgentRunEntity,
    *,
    limit: int,
) -> tuple[AgentRunEntity | None, list[AgentRunEntity]]:
    """
    Find prior successful runs with conversation memory for an agent run.
    
    Parameters:
        run (AgentRunEntity): Run whose workspace, agent, consumer, access source, and conversation define the search scope.
        limit (int): Maximum number of memory runs to return.
    
    Returns:
        tuple[AgentRunEntity | None, list[AgentRunEntity]]: The latest qualifying run with a context summary and the subsequent qualifying runs in chronological order.
    """
    scope = (
        AgentRun.workspace_id == run.workspace_id,
        AgentRun.agent_id == run.agent_id,
        AgentRun.access_source == run.access_source,
        AgentRun.consumer_id == run.consumer_id,
        AgentRun.conversation_id == run.conversation_id,
    )
    successor = aliased(AgentRun)
    successor_state = aliased(AgentRunState)
    before_current = or_(
        AgentRun.created_at < run.created_at,
        and_(AgentRun.created_at == run.created_at, AgentRun.id < run.id),
    )
    anchor_row = (
        await db.execute(
        _memory_run_query()
        .where(
            *scope,
            AgentRunState.status == AGENT_RUN_SUCCEEDED_STATUS,
            AgentRunState.context_summary != "",
            before_current,
            ~exists(
                select(successor.id)
                .join(successor_state, successor_state.run_id == successor.id)
                .where(
                    successor.regenerated_from_run_id == AgentRun.id,
                    successor_state.status.notin_(
                        (AGENT_RUN_FAILED_STATUS, AGENT_RUN_CANCELLED_STATUS)
                    ),
                )
            ),
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
        )
    ).mappings().first()
    after_anchor = None
    if anchor_row is not None:
        anchor_run = _to_memory_run_entity(anchor_row)
        after_anchor = or_(
            AgentRun.created_at > anchor_run.created_at,
            and_(
                AgentRun.created_at == anchor_run.created_at,
                AgentRun.id > anchor_run.id,
            ),
        )
    statement = (
        _memory_run_query()
        .where(
            *scope,
            AgentRunState.status == AGENT_RUN_SUCCEEDED_STATUS,
            before_current,
            ~exists(
                select(successor.id)
                .join(successor_state, successor_state.run_id == successor.id)
                .where(
                    successor.regenerated_from_run_id == AgentRun.id,
                    successor_state.status.notin_(
                        (AGENT_RUN_FAILED_STATUS, AGENT_RUN_CANCELLED_STATUS),
                    ),
                )
            ),
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
    )
    if after_anchor is not None:
        statement = statement.where(after_anchor)
    rows = (await db.execute(statement)).mappings().all()
    return (
        _to_memory_run_entity(anchor_row)
        if anchor_row is not None
        else None,
        [_to_memory_run_entity(row) for row in reversed(rows)],
    )


async def save_conversation_summary(
    db: AsyncSession,
    anchor_run: AgentRunEntity,
    summary: str,
) -> bool:
    updated = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == anchor_run.id,
            AgentRunState.workspace_id == anchor_run.workspace_id,
            AgentRunState.agent_id == anchor_run.agent_id,
            AgentRunState.access_source == anchor_run.access_source,
            AgentRunState.consumer_id == anchor_run.consumer_id,
            AgentRunState.conversation_id == anchor_run.conversation_id,
            AgentRunState.status == AGENT_RUN_SUCCEEDED_STATUS,
        )
        .values(
            context_summary=summary,
            state_version=AgentRunState.state_version + 1,
            updated_at=func.now(),
        )
    )
    if not updated.rowcount:
        return False
    await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.workspace_id == anchor_run.workspace_id,
            AgentRunState.agent_id == anchor_run.agent_id,
            AgentRunState.access_source == anchor_run.access_source,
            AgentRunState.consumer_id == anchor_run.consumer_id,
            AgentRunState.conversation_id == anchor_run.conversation_id,
            AgentRunState.run_id != anchor_run.id,
            AgentRunState.context_summary != "",
        )
        .values(
            context_summary="",
            state_version=AgentRunState.state_version + 1,
            updated_at=func.now(),
        )
    )
    return True


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


async def get_agent_child_run(
    db: AsyncSession,
    workspace_id: str,
    parent_run_id: str,
    parent_node_id: str,
) -> AgentRunEntity | None:
    row = (
        await db.execute(
        _run_query().where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.parent_run_id == parent_run_id,
            AgentRun.parent_node_id == parent_node_id,
        )
        )
    ).first()
    if row is None:
        return None
    return (await _to_agent_run_entities(db, [tuple(row)]))[0]


async def list_agent_child_runs(
    db: AsyncSession,
    workspace_id: str,
    parent_run_id: str,
) -> list[AgentRunEntity]:
    rows = await db.execute(
        _run_query()
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.parent_run_id == parent_run_id,
        )
        .order_by(AgentRun.created_at, AgentRun.id)
    )
    return await _to_agent_run_entities(db, [tuple(row) for row in rows.all()])


async def list_terminal_children_for_waiting_parents(
    db: AsyncSession,
    limit: int = 200,
) -> list[AgentRunEntity]:
    parent = aliased(AgentRun)
    parent_state = aliased(AgentRunState)
    rows = await db.execute(
        _run_query()
        .join(
            parent,
            and_(
                parent.workspace_id == AgentRun.workspace_id,
                parent.id == AgentRun.parent_run_id,
            ),
        )
        .join(parent_state, parent_state.run_id == parent.id)
        .where(
            AgentRunState.status.in_(
                (
                    AGENT_RUN_SUCCEEDED_STATUS,
                    AGENT_RUN_FAILED_STATUS,
                    AGENT_RUN_CANCELLED_STATUS,
                )
            ),
            parent_state.status.in_(AGENT_RUN_AWAITING_CHILD_STATUSES),
        )
        .order_by(AgentRunState.finished_at, AgentRun.id)
        .limit(limit)
    )
    return await _to_agent_run_entities(db, [tuple(row[:3]) for row in rows.all()])


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


async def claim_agent_run(
    db: AsyncSession,
    run_id: str,
    worker_task_id: str,
    started_at: datetime,
    lease_expires_at: datetime,
    *,
    generation: str = "legacy",
) -> bool:
    claimable_statuses = (
        AGENT_RUN_UNIFIED_CLAIMABLE_STATUSES
        if generation == "unified"
        else AGENT_RUN_LEGACY_CLAIMABLE_STATUSES
    )
    running_status = (
        AGENT_RUN_UNIFIED_RUNNING_STATUS
        if generation == "unified"
        else AGENT_RUN_RUNNING_STATUS
    )
    result = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.worker_generation == generation,
            AgentRunState.attempts < AgentRunState.max_attempts,
            or_(
                AgentRunState.status == claimable_statuses[0],
                and_(
                    AgentRunState.status == claimable_statuses[1],
                    or_(
                        AgentRunState.lease_expires_at.is_(None),
                        AgentRunState.lease_expires_at <= started_at,
                    ),
                ),
            ),
        )
        .values(
            status=running_status,
            attempts=AgentRunState.attempts + 1,
            state_version=AgentRunState.state_version + 1,
            worker_task_id=worker_task_id,
            lease_expires_at=lease_expires_at,
            started_at=func.coalesce(AgentRunState.started_at, started_at),
            finished_at=None,
            updated_at=started_at,
        )
    )
    return bool(result.rowcount)


async def renew_agent_run_lease(
    db: AsyncSession,
    run_id: str,
    worker_task_id: str,
    lease_expires_at: datetime,
) -> bool:
    result = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRunState.worker_task_id == worker_task_id,
        )
        .values(
            lease_expires_at=lease_expires_at,
            state_version=AgentRunState.state_version + 1,
            updated_at=func.now(),
        )
    )
    return bool(result.rowcount)


async def save_agent_run_checkpoint(
    db: AsyncSession,
    run_id: str,
    worker_task_id: str,
    checkpoint: dict,
    checkpoint_phase: str,
) -> bool:
    values = {
        "checkpoint": checkpoint,
        "checkpoint_phase": checkpoint_phase,
        "state_version": AgentRunState.state_version + 1,
        "updated_at": func.now(),
    }
    if "model_usage" in checkpoint:
        values["model_usage"] = checkpoint["model_usage"]
    if "grounding_status" in checkpoint:
        values["grounding_status"] = checkpoint["grounding_status"]
    if "grounding_meta" in checkpoint:
        values["grounding_meta"] = checkpoint["grounding_meta"] or {}
    result = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRunState.worker_task_id == worker_task_id,
        )
        .values(**values)
    )
    return bool(result.rowcount)


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


async def requeue_owned_agent_run(
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
                    AGENT_RUN_UNIFIED_QUEUED_STATUS,
                ),
                else_=AGENT_RUN_QUEUED_STATUS,
            ),
            attempts=case(
                (AgentRunState.attempts > 0, AgentRunState.attempts - 1),
                else_=0,
            ),
            state_version=AgentRunState.state_version + 1,
            worker_task_id=None,
            lease_expires_at=None,
            updated_at=func.now(),
        )
    )
    return bool(updated.rowcount)


async def queue_agent_run(
    db: AsyncSession,
    run_id: str,
) -> bool:
    updated = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_AWAITING_APPROVAL_STATUSES),
        )
        .values(
            status=case(
                (
                    AgentRunState.worker_generation == "unified",
                    AGENT_RUN_UNIFIED_QUEUED_STATUS,
                ),
                else_=AGENT_RUN_QUEUED_STATUS,
            ),
            state_version=AgentRunState.state_version + 1,
            last_error=None,
            worker_task_id=None,
            lease_expires_at=None,
            updated_at=func.now(),
        )
    )
    return bool(updated.rowcount)


async def queue_agent_run_from_input(
    db: AsyncSession,
    run_id: str,
    checkpoint: dict,
) -> bool:
    updated = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_AWAITING_INPUT_STATUSES),
        )
        .values(
            status=case(
                (
                    AgentRunState.worker_generation == "unified",
                    AGENT_RUN_UNIFIED_QUEUED_STATUS,
                ),
                else_=AGENT_RUN_QUEUED_STATUS,
            ),
            checkpoint=checkpoint,
            state_version=AgentRunState.state_version + 1,
            last_error=None,
            worker_task_id=None,
            lease_expires_at=None,
            updated_at=func.now(),
        )
    )
    return bool(updated.rowcount)


async def queue_agent_run_from_child(
    db: AsyncSession,
    run_id: str,
) -> bool:
    updated = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_AWAITING_CHILD_STATUSES),
        )
        .values(
            status=case(
                (
                    AgentRunState.worker_generation == "unified",
                    AGENT_RUN_UNIFIED_QUEUED_STATUS,
                ),
                else_=AGENT_RUN_QUEUED_STATUS,
            ),
            state_version=AgentRunState.state_version + 1,
            last_error=None,
            worker_task_id=None,
            lease_expires_at=None,
            updated_at=func.now(),
        )
    )
    return bool(updated.rowcount)


async def fail_agent_run_waiting_for_child(
    db: AsyncSession,
    run_id: str,
    error: str,
    finished_at: datetime,
) -> bool:
    updated = await db.execute(
        update(AgentRunState)
        .where(
            AgentRunState.run_id == run_id,
            AgentRunState.status.in_(AGENT_RUN_AWAITING_CHILD_STATUSES),
        )
        .values(
            status=AGENT_RUN_FAILED_STATUS,
            state_version=AgentRunState.state_version + 1,
            last_error=error,
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=finished_at,
            updated_at=finished_at,
        )
    )
    return bool(updated.rowcount)


async def cancel_agent_run_tree(
    db: AsyncSession,
    run_id: str,
    finished_at: datetime,
) -> list[str]:
    cancelled = list(
        await db.scalars(
            select(AgentRun.id)
            .join(AgentRunState, AgentRunState.run_id == AgentRun.id)
            .where(
                or_(AgentRun.id == run_id, AgentRun.root_run_id == run_id),
                AgentRunState.status.in_(AGENT_RUN_ACTIVE_STATUSES),
            )
            .with_for_update()
        )
    )
    if not cancelled:
        return []
    await db.execute(
        update(AgentRunState)
        .where(AgentRunState.run_id.in_(cancelled))
        .values(
            status=AGENT_RUN_CANCELLED_STATUS,
            state_version=AgentRunState.state_version + 1,
            last_error="Cancelled by user.",
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=finished_at,
            updated_at=finished_at,
        )
    )
    from app.infrastructure.repositories import tools as tool_repository

    await tool_repository.settle_cancelled_agent_tool_invocations(
        db, cancelled, finished_at
    )
    await db.execute(
        update(WorkflowNodeExecution)
        .where(
            WorkflowNodeExecution.run_id.in_(cancelled),
            WorkflowNodeExecution.status.in_(
                ("running", "awaiting_input", "awaiting_child")
            ),
        )
        .values(
            status="failed",
            error="Workflow run was cancelled.",
            finished_at=finished_at,
            updated_at=finished_at,
        )
    )
    return cancelled


async def list_recoverable_agent_run_ids(
    db: AsyncSession,
    now: datetime,
    limit: int = 200,
    *,
    generation: str = "legacy",
) -> list[str]:
    claimable_statuses = (
        AGENT_RUN_UNIFIED_CLAIMABLE_STATUSES
        if generation == "unified"
        else AGENT_RUN_LEGACY_CLAIMABLE_STATUSES
    )
    rows = await db.scalars(
        select(AgentRunState.run_id)
        .join(AgentRun, AgentRun.id == AgentRunState.run_id)
        .where(
            AgentRunState.worker_generation == generation,
            AgentRunState.attempts < AgentRunState.max_attempts,
            or_(
                AgentRunState.status == claimable_statuses[0],
                and_(
                    AgentRunState.status == claimable_statuses[1],
                    or_(
                        AgentRunState.lease_expires_at.is_(None),
                        AgentRunState.lease_expires_at <= now,
                    ),
                ),
            ),
        )
        .order_by(AgentRun.created_at, AgentRun.id)
        .limit(limit)
    )
    return list(rows.all())


async def fail_exhausted_agent_run_ids(
    db: AsyncSession,
    now: datetime,
    *,
    generation: str = "legacy",
) -> list[str]:
    claimable_statuses = (
        AGENT_RUN_UNIFIED_CLAIMABLE_STATUSES
        if generation == "unified"
        else AGENT_RUN_LEGACY_CLAIMABLE_STATUSES
    )
    updated = await db.scalars(
        update(AgentRunState)
        .where(
            AgentRunState.worker_generation == generation,
            AgentRunState.attempts >= AgentRunState.max_attempts,
            or_(
                AgentRunState.status == claimable_statuses[0],
                and_(
                    AgentRunState.status == claimable_statuses[1],
                    or_(
                        AgentRunState.lease_expires_at.is_(None),
                        AgentRunState.lease_expires_at <= now,
                    ),
                ),
            ),
        )
        .values(
            status=AGENT_RUN_FAILED_STATUS,
            state_version=AgentRunState.state_version + 1,
            last_error="Agent run retry limit reached.",
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=now,
            updated_at=now,
        )
        .returning(AgentRunState.run_id)
    )
    exhausted_run_ids = list(updated.all())
    if not exhausted_run_ids:
        return []
    from app.infrastructure.repositories import tools as tool_repository

    await tool_repository.settle_exhausted_agent_tool_invocations(
        db, exhausted_run_ids, now
    )
    await db.execute(
        update(WorkflowNodeExecution)
        .where(
            WorkflowNodeExecution.run_id.in_(exhausted_run_ids),
            WorkflowNodeExecution.status == "running",
        )
        .values(
            status="failed",
            error=(
                "Workflow run retry limit reached before the node result was "
                "durably recorded."
            ),
            finished_at=now,
            updated_at=now,
        )
    )
    return exhausted_run_ids


async def fail_exhausted_agent_runs(db: AsyncSession, now: datetime) -> int:
    return len(await fail_exhausted_agent_run_ids(db, now))


async def append_agent_run_event(
    db: AsyncSession,
    workspace_id: str,
    run_id: str,
    event: dict,
) -> AgentRunEventEntity:
    row = AgentRunEvent(workspace_id=workspace_id, run_id=run_id, event=event)
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
    return [to_entity(AgentRunEventEntity, row) for row in rows.all()]


def _internal_tool_metadata(invocation: ToolInvocation) -> dict[str, Any]:
    metadata = invocation.policy_snapshot.get("internal_tool", {})
    return metadata if isinstance(metadata, dict) else {}


def _is_internal_tool_invocation(invocation: ToolInvocation) -> bool:
    return invocation.policy_snapshot.get("ledger_kind") == _INTERNAL_TOOL_LEDGER


def _tool_invocation_status(status: str) -> str:
    return "queued" if status == "pending" else status


def _agent_tool_call_status(status: str) -> str:
    return "pending" if status == "queued" else status


def _normalized_arguments_hash(
    arguments: dict[str, Any],
    value: str,
) -> str:
    if len(value) == 64:
        return value
    return hashlib.sha256(
        json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _internal_tool_idempotency_key(entity: AgentToolCallEntity) -> str:
    if entity.idempotency_key:
        return entity.idempotency_key
    return hashlib.sha256(
        f"agent-internal:{entity.run_id}:{entity.turn}:{entity.call_id}".encode()
    ).hexdigest()


def _to_agent_tool_call_entity(invocation: ToolInvocation) -> AgentToolCallEntity:
    metadata = _internal_tool_metadata(invocation)
    result = invocation.result_data if isinstance(invocation.result_data, dict) else {}
    return AgentToolCallEntity(
        id=invocation.id,
        workspace_id=invocation.workspace_id,
        run_id=invocation.run_id or "",
        turn=int(metadata.get("turn", 0)),
        call_id=str(metadata.get("call_id", invocation.invocation_id)),
        tool_name=str(metadata.get("tool_name", "")),
        tool_kind=str(metadata.get("tool_kind", "unknown")),
        server_name=str(metadata.get("server_name", "")),
        arguments=invocation.arguments,
        arguments_hash=invocation.arguments_hash,
        definition_hash=str(metadata.get("definition_hash", "")),
        policy_mode=str(metadata.get("policy_mode", "")),
        idempotency_key=invocation.idempotency_key,
        status=_agent_tool_call_status(invocation.status),
        approval_required=bool(metadata.get("approval_required", False)),
        approved_by_user_id=invocation.approved_by_user_id,
        approved_at=invocation.approved_at,
        worker_task_id=invocation.worker_task_id,
        lease_expires_at=invocation.lease_expires_at,
        result_content=str(result.get("content", "")),
        result_summary=invocation.result_summary,
        result_output=result.get("output"),
        result_is_error=bool(result.get("is_error", False)),
        result_evidence_ids=list(result.get("evidence_ids", [])),
        last_error=invocation.error_message,
        started_at=invocation.started_at,
        finished_at=invocation.finished_at,
        created_at=invocation.created_at,
        updated_at=invocation.updated_at,
    )


async def get_agent_tool_call(
    db: AsyncSession,
    run_id: str,
    turn: int,
    call_id: str,
) -> AgentToolCallEntity | None:
    row = await db.scalar(
        select(ToolInvocation).where(
            ToolInvocation.run_id == run_id,
            ToolInvocation.invocation_id == f"{turn}:{call_id}",
        )
    )
    if row is None or not _is_internal_tool_invocation(row):
        return None
    return _to_agent_tool_call_entity(row)


async def get_agent_tool_call_by_call_id(
    db: AsyncSession,
    run_id: str,
    call_id: str,
) -> AgentToolCallEntity | None:
    rows = await db.scalars(
        select(ToolInvocation)
        .where(ToolInvocation.run_id == run_id)
        .order_by(ToolInvocation.created_at.desc(), ToolInvocation.id.desc())
    )
    for row in rows.all():
        if (
            _is_internal_tool_invocation(row)
            and _internal_tool_metadata(row).get("call_id") == call_id
        ):
            return _to_agent_tool_call_entity(row)
    return None


async def list_agent_tool_calls(
    db: AsyncSession,
    run_id: str,
) -> list[AgentToolCallEntity]:
    rows = await db.scalars(
        select(ToolInvocation)
        .where(ToolInvocation.run_id == run_id)
        .order_by(ToolInvocation.created_at, ToolInvocation.id)
    )
    calls = [
        _to_agent_tool_call_entity(row)
        for row in rows.all()
        if _is_internal_tool_invocation(row)
    ]
    return sorted(calls, key=lambda call: (call.turn, call.created_at, call.id))


async def create_agent_tool_call(
    db: AsyncSession,
    entity: AgentToolCallEntity,
) -> AgentToolCallEntity:
    run = await db.get(AgentRun, entity.run_id)
    if run is None:
        raise RuntimeError("Agent run no longer exists.")
    from app.infrastructure.repositories import tools as tool_repository

    effect = (
        "pure"
        if entity.tool_kind == "knowledge"
        else "external_write"
        if entity.approval_required
        else "external_read"
    )
    await tool_repository.create_or_get_tool_invocation(
        db,
        ToolInvocationEntity(
            id=entity.id,
            workspace_id=entity.workspace_id,
            origin="agent",
            root_run_id=run.root_run_id,
            run_id=entity.run_id,
            invocation_id=f"{entity.turn}:{entity.call_id}",
            execution_user_id=run.execution_user_id,
            access_source=run.access_source,
            tool_id=None,
            tool_version_id=None,
            policy_snapshot={
                "ledger_kind": _INTERNAL_TOOL_LEDGER,
                "internal_tool": {
                    "turn": entity.turn,
                    "call_id": entity.call_id,
                    "tool_name": entity.tool_name,
                    "tool_kind": entity.tool_kind,
                    "server_name": entity.server_name,
                    "definition_hash": entity.definition_hash,
                    "policy_mode": entity.policy_mode,
                    "approval_required": entity.approval_required,
                    "effect": effect,
                },
            },
            arguments=entity.arguments,
            arguments_hash=_normalized_arguments_hash(
                entity.arguments, entity.arguments_hash
            ),
            idempotency_key=_internal_tool_idempotency_key(entity),
            status=_tool_invocation_status(entity.status),
            approved_by_user_id=entity.approved_by_user_id,
            approved_at=entity.approved_at,
            worker_task_id=entity.worker_task_id,
            lease_expires_at=(
                entity.lease_expires_at if entity.worker_task_id else None
            ),
            result_data={
                "content": entity.result_content,
                "output": entity.result_output,
                "is_error": entity.result_is_error,
                "evidence_ids": entity.result_evidence_ids,
            },
            result_summary=entity.result_summary,
            outcome=(
                "uncertain"
                if entity.status == "uncertain"
                else "confirmed"
                if entity.status in {"succeeded", "failed", "rejected"}
                else None
            ),
            error_message=entity.last_error,
            started_at=entity.started_at,
            finished_at=entity.finished_at,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        ),
    )
    current = await get_agent_tool_call(db, entity.run_id, entity.turn, entity.call_id)
    assert current is not None
    return current


async def claim_agent_tool_call(
    db: AsyncSession,
    tool_call_id: str,
    worker_task_id: str,
    started_at: datetime,
    lease_expires_at: datetime,
) -> bool:
    updated = await db.execute(
        update(ToolInvocation)
        .where(
            ToolInvocation.id == tool_call_id,
            ToolInvocation.status.in_(("queued", "approved")),
            ToolInvocation.attempts < ToolInvocation.max_attempts,
        )
        .values(
            status="running",
            attempts=ToolInvocation.attempts + 1,
            worker_task_id=worker_task_id,
            lease_expires_at=lease_expires_at,
            started_at=func.coalesce(ToolInvocation.started_at, started_at),
            updated_at=started_at,
        )
    )
    return bool(updated.rowcount)


async def save_agent_tool_call_result(
    db: AsyncSession,
    tool_call_id: str,
    worker_task_id: str,
    result: AgentToolCallEntity,
) -> bool:
    updated = await db.execute(
        update(ToolInvocation)
        .where(
            ToolInvocation.id == tool_call_id,
            ToolInvocation.status == "running",
            ToolInvocation.worker_task_id == worker_task_id,
        )
        .values(
            status=result.status,
            result_data={
                "content": result.result_content,
                "output": result.result_output,
                "is_error": result.result_is_error,
                "evidence_ids": result.result_evidence_ids,
            },
            result_summary=result.result_summary,
            outcome="uncertain" if result.status == "uncertain" else "confirmed",
            error_code="agent_tool_error" if result.last_error else None,
            error_message=result.last_error,
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=result.finished_at,
            updated_at=result.updated_at,
        )
    )
    return bool(updated.rowcount)


async def mark_expired_agent_tool_calls(
    db: AsyncSession,
    run_id: str,
    now: datetime,
) -> None:
    rows = await db.scalars(
        select(ToolInvocation)
        .where(
            ToolInvocation.run_id == run_id,
            ToolInvocation.status == "running",
            or_(
                ToolInvocation.lease_expires_at.is_(None),
                ToolInvocation.lease_expires_at <= now,
            ),
        )
        .with_for_update()
    )
    for row in rows.all():
        if not _is_internal_tool_invocation(row):
            continue
        approval_required = bool(
            _internal_tool_metadata(row).get("approval_required", False)
        )
        row.status = "uncertain" if approval_required else "approved"
        row.error_message = (
            "Tool execution was interrupted after dispatch; confirm the external state "
            "before retrying."
            if approval_required
            else None
        )
        row.worker_task_id = None
        row.lease_expires_at = None
        row.updated_at = now
    await db.flush()


async def approve_agent_tool_call(
    db: AsyncSession,
    tool_call_id: str,
    actor_id: str,
    approved_at: datetime,
) -> bool:
    updated = await db.execute(
        update(ToolInvocation)
        .where(
            ToolInvocation.id == tool_call_id,
            ToolInvocation.status == "awaiting_approval",
        )
        .values(
            status="approved",
            approved_by_user_id=actor_id,
            approved_at=approved_at,
            error_code=None,
            error_message=None,
            updated_at=approved_at,
        )
    )
    return bool(updated.rowcount)


async def reject_agent_tool_call(
    db: AsyncSession,
    tool_call_id: str,
    actor_id: str,
    rejected_at: datetime,
) -> bool:
    updated = await db.execute(
        update(ToolInvocation)
        .where(
            ToolInvocation.id == tool_call_id,
            ToolInvocation.status.in_(("awaiting_approval", "uncertain")),
        )
        .values(
            status="rejected",
            approved_by_user_id=actor_id,
            approved_at=rejected_at,
            result_summary="Tool call rejected by user.",
            outcome="confirmed",
            error_code="tool_call_rejected",
            error_message="Tool call rejected by user.",
            finished_at=rejected_at,
            updated_at=rejected_at,
        )
    )
    return bool(updated.rowcount)


async def block_agent_tool_call(
    db: AsyncSession,
    tool_call_id: str,
    reason: str,
    blocked_at: datetime,
    result_summary: str,
) -> bool:
    updated = await db.execute(
        update(ToolInvocation)
        .where(
            ToolInvocation.id == tool_call_id,
            ToolInvocation.status.in_(
                ("queued", "awaiting_approval", "approved")
            ),
        )
        .values(
            status="rejected",
            result_data={
                "content": reason,
                "output": None,
                "is_error": True,
                "evidence_ids": [],
            },
            result_summary=result_summary,
            outcome="confirmed",
            error_code="tool_call_blocked",
            error_message=reason,
            finished_at=blocked_at,
            updated_at=blocked_at,
        )
    )
    return bool(updated.rowcount)


async def require_agent_tool_call_approval(
    db: AsyncSession,
    tool_call_id: str,
    policy_mode: str,
    updated_at: datetime,
) -> bool:
    row = await db.scalar(
        select(ToolInvocation)
        .where(
            ToolInvocation.id == tool_call_id,
            ToolInvocation.status.in_(("queued", "approved")),
            ToolInvocation.approved_by_user_id.is_(None),
        )
        .with_for_update()
    )
    if row is None or not _is_internal_tool_invocation(row):
        return False
    metadata = _internal_tool_metadata(row)
    row.policy_snapshot = {
        **row.policy_snapshot,
        "internal_tool": {
            **metadata,
            "approval_required": True,
            "policy_mode": policy_mode,
            "effect": "external_write",
        },
    }
    row.status = "awaiting_approval"
    row.updated_at = updated_at
    await db.flush()
    return True


async def delete_agent_graph(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    resource_type: str,
) -> None:
    await db.execute(delete(AgentRun).where(AgentRun.agent_id == agent_id))
    await db.execute(
        delete(AgentApiCredential).where(AgentApiCredential.agent_id == agent_id)
    )
    await db.execute(delete(AgentMcpTool).where(AgentMcpTool.agent_id == agent_id))
    await db.execute(
        delete(AgentKnowledgeBase).where(AgentKnowledgeBase.agent_id == agent_id)
    )
    await db.execute(
        delete(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == agent_id,
        )
    )
    await db.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(current_published_version_id=None)
    )
    await db.execute(delete(Agent).where(Agent.id == agent_id))


async def has_unsettled_agent_execution(
    db: AsyncSession,
    agent_id: str,
) -> bool:
    active_run = await db.scalar(
        select(AgentRun.id)
        .join(AgentRunState, AgentRunState.run_id == AgentRun.id)
        .where(
            AgentRun.agent_id == agent_id,
            AgentRunState.status.in_(AGENT_RUN_ACTIVE_STATUSES),
        )
        .limit(1)
    )
    if active_run is not None:
        return True
    unsettled_call = await db.scalar(
        select(ToolInvocation.id)
        .join(AgentRun, AgentRun.id == ToolInvocation.run_id)
        .where(
            AgentRun.agent_id == agent_id,
            ToolInvocation.status.in_(
                ("queued", "approved", "running", "awaiting_approval")
            ),
        )
        .limit(1)
    )
    return unsettled_call is not None


async def list_agent_run_ids(db: AsyncSession, agent_id: str) -> list[str]:
    rows = await db.scalars(select(AgentRun.id).where(AgentRun.agent_id == agent_id))
    return list(rows.all())


async def delete_workspace_agent_graph(db: AsyncSession, workspace_id: str) -> None:
    await db.execute(delete(AgentRun).where(AgentRun.workspace_id == workspace_id))
    await db.execute(
        delete(AgentApiCredential).where(
            AgentApiCredential.workspace_id == workspace_id
        )
    )
    await db.execute(
        delete(AgentMcpTool).where(AgentMcpTool.workspace_id == workspace_id)
    )
    await db.execute(
        delete(AgentKnowledgeBase).where(
            AgentKnowledgeBase.workspace_id == workspace_id
        )
    )
    await db.execute(
        update(Agent)
        .where(Agent.workspace_id == workspace_id)
        .values(current_published_version_id=None)
    )
    await db.execute(delete(Agent).where(Agent.workspace_id == workspace_id))
