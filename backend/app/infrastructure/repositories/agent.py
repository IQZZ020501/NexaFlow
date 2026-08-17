from datetime import datetime

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from app.domain.resource_permission import ResourcePermission as ResourcePermissionORM
from app.entities.agents import Agent as AgentEntity
from app.entities.agents import AgentApiCredential as AgentApiCredentialEntity
from app.entities.agents import (
    AgentPublicationVersion as AgentPublicationVersionEntity,
)
from app.entities.agents import AgentRun as AgentRunEntity
from app.entities.agents import AgentRunEvent as AgentRunEventEntity
from app.entities.agents import AgentToolCall as AgentToolCallEntity
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
    AgentToolCall,
)
from app.shareddomain.workflows.models import WorkflowNodeExecution

_CONVERSATION_MEMORY_COLUMNS = (
    AgentRun.id,
    AgentRun.workspace_id,
    AgentRun.agent_id,
    AgentRun.requested_by_user_id,
    AgentRun.execution_user_id,
    AgentRun.access_source,
    AgentRun.consumer_id,
    AgentRun.conversation_id,
    AgentRun.status,
    AgentRun.goal,
    AgentRun.attachment_context,
    AgentRun.result,
    AgentRun.context_summary,
    AgentRun.created_at,
)


def _to_conversation_memory_entity(row: AgentRun) -> AgentRunEntity:
    return AgentRunEntity(
        id=row.id,
        workspace_id=row.workspace_id,
        agent_id=row.agent_id,
        requested_by_user_id=row.requested_by_user_id,
        execution_user_id=row.execution_user_id,
        access_source=row.access_source,
        consumer_id=row.consumer_id,
        conversation_id=row.conversation_id,
        status=row.status,
        goal=row.goal,
        attachment_context=row.attachment_context,
        result=row.result,
        context_summary=row.context_summary,
        created_at=row.created_at,
    )


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
    run_snapshots = await db.scalars(select(AgentRun.tool_snapshots))
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
) -> list[AgentRunEntity]:
    statement = (
        select(AgentRun)
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
        statement = statement.where(AgentRun.status.in_(agent_run_storage_statuses(status)))
    if conversation_id is not None:
        statement = statement.where(AgentRun.conversation_id == conversation_id)
    result = await db.scalars(statement)
    return [to_entity(AgentRunEntity, row) for row in result.all()]


async def count_agent_runs(
    db: AsyncSession,
    agent_id: str,
    *,
    access_source: str | None = None,
    consumer_id: str | None = None,
    conversation_id: str | None = None,
) -> int:
    statement = select(func.count()).select_from(AgentRun).where(
        AgentRun.agent_id == agent_id
    )
    if access_source is not None:
        statement = statement.where(AgentRun.access_source == access_source)
    if consumer_id is not None:
        statement = statement.where(AgentRun.consumer_id == consumer_id)
    if conversation_id is not None:
        statement = statement.where(AgentRun.conversation_id == conversation_id)
    return int(await db.scalar(statement) or 0)


async def list_agent_runs_for_management(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    limit: int,
    offset: int,
) -> list[AgentRunEntity]:
    rows = await db.scalars(
        select(AgentRun)
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.agent_id == agent_id,
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(AgentRunEntity, row) for row in rows.all()]


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
            AgentRun.status,
            AgentRun.model_usage,
        ).where(
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
    scope = (
        AgentRun.agent_id == agent_id,
        AgentRun.access_source == access_source,
        AgentRun.consumer_id == consumer_id,
    )
    aggregates = (
        select(
            AgentRun.conversation_id.label("conversation_id"),
            func.count().label("run_count"),
            func.min(AgentRun.created_at).label("created_at"),
            func.max(AgentRun.updated_at).label("updated_at"),
        )
        .where(*scope)
        .group_by(AgentRun.conversation_id)
        .subquery()
    )
    ranked = (
        select(
            AgentRun.id.label("run_id"),
            AgentRun.conversation_id.label("conversation_id"),
            AgentRun.goal.label("goal"),
            AgentRun.status.label("status"),
            AgentRun.result.label("result"),
            func.row_number()
            .over(
                partition_by=AgentRun.conversation_id,
                order_by=(AgentRun.created_at.desc(), AgentRun.id.desc()),
            )
            .label("rank"),
        )
        .where(*scope)
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
    row = await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.agent_id == agent_id,
            AgentRun.access_source == access_source,
            AgentRun.consumer_id == consumer_id,
            AgentRun.conversation_id == conversation_id,
            AgentRun.status.in_(AGENT_RUN_ACTIVE_STATUSES),
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    return to_entity(AgentRunEntity, row) if row is not None else None


async def list_conversation_memory_runs(
    db: AsyncSession,
    run: AgentRunEntity,
    *,
    limit: int,
) -> tuple[AgentRunEntity | None, list[AgentRunEntity]]:
    scope = (
        AgentRun.workspace_id == run.workspace_id,
        AgentRun.agent_id == run.agent_id,
        AgentRun.access_source == run.access_source,
        AgentRun.consumer_id == run.consumer_id,
        AgentRun.conversation_id == run.conversation_id,
    )
    before_current = or_(
        AgentRun.created_at < run.created_at,
        and_(AgentRun.created_at == run.created_at, AgentRun.id < run.id),
    )
    anchor_row = await db.scalar(
        select(AgentRun)
        .options(load_only(*_CONVERSATION_MEMORY_COLUMNS))
        .where(
            *scope,
            AgentRun.status == AGENT_RUN_SUCCEEDED_STATUS,
            AgentRun.context_summary != "",
            before_current,
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    after_anchor = None
    if anchor_row is not None:
        after_anchor = or_(
            AgentRun.created_at > anchor_row.created_at,
            and_(
                AgentRun.created_at == anchor_row.created_at,
                AgentRun.id > anchor_row.id,
            ),
        )
    statement = (
        select(AgentRun)
        .options(load_only(*_CONVERSATION_MEMORY_COLUMNS))
        .where(
            *scope,
            AgentRun.status == AGENT_RUN_SUCCEEDED_STATUS,
            before_current,
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
    )
    if after_anchor is not None:
        statement = statement.where(after_anchor)
    rows = await db.scalars(statement)
    return (
        _to_conversation_memory_entity(anchor_row)
        if anchor_row is not None
        else None,
        [_to_conversation_memory_entity(row) for row in reversed(rows.all())],
    )


async def save_conversation_summary(
    db: AsyncSession,
    anchor_run: AgentRunEntity,
    summary: str,
) -> bool:
    updated = await db.execute(
        update(AgentRun)
        .where(
            AgentRun.id == anchor_run.id,
            AgentRun.workspace_id == anchor_run.workspace_id,
            AgentRun.agent_id == anchor_run.agent_id,
            AgentRun.access_source == anchor_run.access_source,
            AgentRun.consumer_id == anchor_run.consumer_id,
            AgentRun.conversation_id == anchor_run.conversation_id,
            AgentRun.status == AGENT_RUN_SUCCEEDED_STATUS,
        )
        .values(context_summary=summary, updated_at=func.now())
    )
    if not updated.rowcount:
        return False
    await db.execute(
        update(AgentRun)
        .where(
            AgentRun.workspace_id == anchor_run.workspace_id,
            AgentRun.agent_id == anchor_run.agent_id,
            AgentRun.access_source == anchor_run.access_source,
            AgentRun.consumer_id == anchor_run.consumer_id,
            AgentRun.conversation_id == anchor_run.conversation_id,
            AgentRun.id != anchor_run.id,
            AgentRun.context_summary != "",
        )
        .values(context_summary="", updated_at=func.now())
    )
    return True


async def get_agent_run_by_id(
    db: AsyncSession,
    run_id: str,
) -> AgentRunEntity | None:
    row = await db.get(AgentRun, run_id)
    return to_entity(AgentRunEntity, row) if row is not None else None


async def create_agent_run(db: AsyncSession, entity: AgentRunEntity) -> AgentRunEntity:
    orm = await save(db, AgentRun, entity)
    return to_entity(AgentRunEntity, orm)


async def get_agent_child_run(
    db: AsyncSession,
    workspace_id: str,
    parent_run_id: str,
    parent_node_id: str,
) -> AgentRunEntity | None:
    row = await db.scalar(
        select(AgentRun).where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.parent_run_id == parent_run_id,
            AgentRun.parent_node_id == parent_node_id,
        )
    )
    return to_entity(AgentRunEntity, row) if row is not None else None


async def list_agent_child_runs(
    db: AsyncSession,
    workspace_id: str,
    parent_run_id: str,
) -> list[AgentRunEntity]:
    rows = await db.scalars(
        select(AgentRun)
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.parent_run_id == parent_run_id,
        )
        .order_by(AgentRun.created_at, AgentRun.id)
    )
    return [to_entity(AgentRunEntity, row) for row in rows.all()]


async def list_terminal_children_for_waiting_parents(
    db: AsyncSession,
    limit: int = 200,
) -> list[AgentRunEntity]:
    parent = aliased(AgentRun)
    rows = await db.scalars(
        select(AgentRun)
        .join(
            parent,
            and_(
                parent.workspace_id == AgentRun.workspace_id,
                parent.id == AgentRun.parent_run_id,
            ),
        )
        .where(
            AgentRun.status.in_(
                (
                    AGENT_RUN_SUCCEEDED_STATUS,
                    AGENT_RUN_FAILED_STATUS,
                    AGENT_RUN_CANCELLED_STATUS,
                )
            ),
            parent.status.in_(AGENT_RUN_AWAITING_CHILD_STATUSES),
        )
        .order_by(AgentRun.finished_at, AgentRun.id)
        .limit(limit)
    )
    return [to_entity(AgentRunEntity, row) for row in rows.all()]


async def save_agent_run(db: AsyncSession, entity: AgentRunEntity) -> AgentRunEntity:
    orm = await save(db, AgentRun, entity)
    return to_entity(AgentRunEntity, orm)


async def refresh_agent_run(db: AsyncSession, entity: AgentRunEntity) -> AgentRunEntity:
    return await refresh_entity(db, AgentRun, AgentRunEntity, entity)


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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.attempts < AgentRun.max_attempts,
            or_(
                AgentRun.status == claimable_statuses[0],
                and_(
                    AgentRun.status == claimable_statuses[1],
                    or_(
                        AgentRun.lease_expires_at.is_(None),
                        AgentRun.lease_expires_at <= started_at,
                    ),
                ),
            ),
        )
        .values(
            status=running_status,
            attempts=AgentRun.attempts + 1,
            worker_task_id=worker_task_id,
            lease_expires_at=lease_expires_at,
            started_at=func.coalesce(AgentRun.started_at, started_at),
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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRun.worker_task_id == worker_task_id,
        )
        .values(lease_expires_at=lease_expires_at, updated_at=func.now())
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
        "updated_at": func.now(),
    }
    if "model_usage" in checkpoint:
        values["model_usage"] = checkpoint["model_usage"]
    result = await db.execute(
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRun.worker_task_id == worker_task_id,
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
) -> bool:
    values = {
        "status": status,
        "result": result,
        "events": events,
        "last_error": last_error,
        "finished_at": finished_at,
        "worker_task_id": None,
        "lease_expires_at": None,
        "updated_at": finished_at,
    }
    if model_usage is not None:
        values["model_usage"] = model_usage
    updated = await db.execute(
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRun.worker_task_id == worker_task_id,
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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRun.worker_task_id == worker_task_id,
        )
        .values(
            status=case(
                (
                    AgentRun.configuration_source.in_(("draft", "published")),
                    AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS,
                ),
                else_=AGENT_RUN_AWAITING_APPROVAL_STATUS,
            ),
            attempts=case(
                (AgentRun.attempts > 0, AgentRun.attempts - 1),
                else_=0,
            ),
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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRun.worker_task_id == worker_task_id,
        )
        .values(
            status=case(
                (
                    AgentRun.configuration_source.in_(("draft", "published")),
                    AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS,
                ),
                else_=AGENT_RUN_AWAITING_INPUT_STATUS,
            ),
            attempts=case(
                (AgentRun.attempts > 0, AgentRun.attempts - 1),
                else_=0,
            ),
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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRun.worker_task_id == worker_task_id,
        )
        .values(
            status=case(
                (
                    AgentRun.configuration_source.in_(("draft", "published")),
                    AGENT_RUN_UNIFIED_AWAITING_CHILD_STATUS,
                ),
                else_=AGENT_RUN_AWAITING_CHILD_STATUS,
            ),
            attempts=case(
                (AgentRun.attempts > 0, AgentRun.attempts - 1),
                else_=0,
            ),
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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRun.worker_task_id == worker_task_id,
        )
        .values(
            status=case(
                (
                    AgentRun.configuration_source.in_(("draft", "published")),
                    AGENT_RUN_UNIFIED_QUEUED_STATUS,
                ),
                else_=AGENT_RUN_QUEUED_STATUS,
            ),
            attempts=case(
                (AgentRun.attempts > 0, AgentRun.attempts - 1),
                else_=0,
            ),
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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_AWAITING_APPROVAL_STATUSES),
        )
        .values(
            status=case(
                (
                    AgentRun.configuration_source.in_(("draft", "published")),
                    AGENT_RUN_UNIFIED_QUEUED_STATUS,
                ),
                else_=AGENT_RUN_QUEUED_STATUS,
            ),
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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_AWAITING_INPUT_STATUSES),
        )
        .values(
            status=case(
                (
                    AgentRun.configuration_source.in_(("draft", "published")),
                    AGENT_RUN_UNIFIED_QUEUED_STATUS,
                ),
                else_=AGENT_RUN_QUEUED_STATUS,
            ),
            checkpoint=checkpoint,
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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_AWAITING_CHILD_STATUSES),
        )
        .values(
            status=case(
                (
                    AgentRun.configuration_source.in_(("draft", "published")),
                    AGENT_RUN_UNIFIED_QUEUED_STATUS,
                ),
                else_=AGENT_RUN_QUEUED_STATUS,
            ),
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
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_AWAITING_CHILD_STATUSES),
        )
        .values(
            status=AGENT_RUN_FAILED_STATUS,
            last_error=error,
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=finished_at,
            updated_at=finished_at,
        )
    )
    return bool(updated.rowcount)


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
        select(AgentRun.id)
        .where(
            AgentRun.attempts < AgentRun.max_attempts,
            or_(
                AgentRun.status == claimable_statuses[0],
                and_(
                    AgentRun.status == claimable_statuses[1],
                    or_(
                        AgentRun.lease_expires_at.is_(None),
                        AgentRun.lease_expires_at <= now,
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
        update(AgentRun)
        .where(
            AgentRun.attempts >= AgentRun.max_attempts,
            or_(
                AgentRun.status == claimable_statuses[0],
                and_(
                    AgentRun.status == claimable_statuses[1],
                    or_(
                        AgentRun.lease_expires_at.is_(None),
                        AgentRun.lease_expires_at <= now,
                    ),
                ),
            ),
        )
        .values(
            status=AGENT_RUN_FAILED_STATUS,
            last_error="Agent run retry limit reached.",
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=now,
            updated_at=now,
        )
        .returning(AgentRun.id)
    )
    exhausted_run_ids = list(updated.all())
    if not exhausted_run_ids:
        return []
    await db.execute(
        update(AgentToolCall)
        .where(
            AgentToolCall.run_id.in_(exhausted_run_ids),
            AgentToolCall.status == "running",
            AgentToolCall.approval_required.is_(False),
        )
        .values(
            status="failed",
            result_content=(
                "Tool execution was interrupted before a durable result was recorded."
            ),
            result_summary="Tool execution interrupted.",
            result_is_error=True,
            last_error=(
                "Agent run retry limit reached before the tool result was durably recorded."
            ),
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=now,
            updated_at=now,
        )
    )
    await db.execute(
        update(AgentToolCall)
        .where(
            AgentToolCall.run_id.in_(exhausted_run_ids),
            AgentToolCall.status == "running",
            AgentToolCall.approval_required.is_(True),
        )
        .values(
            status="uncertain",
            last_error=(
                "Tool execution was interrupted after dispatch; confirm the external state."
            ),
            worker_task_id=None,
            lease_expires_at=None,
            finished_at=now,
            updated_at=now,
        )
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
        select(AgentRun)
        .where(
            AgentRun.workspace_id == workspace_id,
            AgentRun.id == run_id,
            AgentRun.status.in_(AGENT_RUN_RUNNING_STATUSES),
            AgentRun.worker_task_id == worker_task_id,
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


async def get_agent_tool_call(
    db: AsyncSession,
    run_id: str,
    turn: int,
    call_id: str,
) -> AgentToolCallEntity | None:
    row = await db.scalar(
        select(AgentToolCall).where(
            AgentToolCall.run_id == run_id,
            AgentToolCall.turn == turn,
            AgentToolCall.call_id == call_id,
        )
    )
    return to_entity(AgentToolCallEntity, row) if row is not None else None


async def get_agent_tool_call_by_call_id(
    db: AsyncSession,
    run_id: str,
    call_id: str,
) -> AgentToolCallEntity | None:
    row = await db.scalar(
        select(AgentToolCall)
        .where(AgentToolCall.run_id == run_id, AgentToolCall.call_id == call_id)
        .order_by(AgentToolCall.turn.desc())
        .limit(1)
    )
    return to_entity(AgentToolCallEntity, row) if row is not None else None


async def list_agent_tool_calls(
    db: AsyncSession,
    run_id: str,
) -> list[AgentToolCallEntity]:
    rows = await db.scalars(
        select(AgentToolCall)
        .where(AgentToolCall.run_id == run_id)
        .order_by(AgentToolCall.turn, AgentToolCall.created_at, AgentToolCall.id)
    )
    return [to_entity(AgentToolCallEntity, row) for row in rows.all()]


async def create_agent_tool_call(
    db: AsyncSession,
    entity: AgentToolCallEntity,
) -> AgentToolCallEntity:
    try:
        async with db.begin_nested():
            row = to_orm(AgentToolCall, entity)
            db.add(row)
            await db.flush()
    except IntegrityError:
        pass
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
        update(AgentToolCall)
        .where(
            AgentToolCall.id == tool_call_id,
            AgentToolCall.status.in_(("pending", "approved")),
        )
        .values(
            status="running",
            worker_task_id=worker_task_id,
            lease_expires_at=lease_expires_at,
            started_at=func.coalesce(AgentToolCall.started_at, started_at),
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
        update(AgentToolCall)
        .where(
            AgentToolCall.id == tool_call_id,
            AgentToolCall.status == "running",
            AgentToolCall.worker_task_id == worker_task_id,
        )
        .values(
            status=result.status,
            result_content=result.result_content,
            result_summary=result.result_summary,
            result_output=result.result_output,
            result_is_error=result.result_is_error,
            result_evidence_ids=result.result_evidence_ids,
            last_error=result.last_error,
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
    await db.execute(
        update(AgentToolCall)
        .where(
            AgentToolCall.run_id == run_id,
            AgentToolCall.status == "running",
            AgentToolCall.approval_required.is_(False),
            or_(
                AgentToolCall.lease_expires_at.is_(None),
                AgentToolCall.lease_expires_at <= now,
            ),
        )
        .values(
            status="approved",
            worker_task_id=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    await db.execute(
        update(AgentToolCall)
        .where(
            AgentToolCall.run_id == run_id,
            AgentToolCall.status == "running",
            AgentToolCall.approval_required.is_(True),
            or_(
                AgentToolCall.lease_expires_at.is_(None),
                AgentToolCall.lease_expires_at <= now,
            ),
        )
        .values(
            status="uncertain",
            last_error=(
                "Tool execution was interrupted after dispatch; confirm the external state "
                "before retrying."
            ),
            worker_task_id=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )


async def approve_agent_tool_call(
    db: AsyncSession,
    tool_call_id: str,
    actor_id: str,
    approved_at: datetime,
) -> bool:
    updated = await db.execute(
        update(AgentToolCall)
        .where(
            AgentToolCall.id == tool_call_id,
            AgentToolCall.status == "awaiting_approval",
        )
        .values(
            status="approved",
            approved_by_user_id=actor_id,
            approved_at=approved_at,
            last_error=None,
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
        update(AgentToolCall)
        .where(
            AgentToolCall.id == tool_call_id,
            AgentToolCall.status.in_(("awaiting_approval", "uncertain")),
        )
        .values(
            status="rejected",
            approved_by_user_id=actor_id,
            approved_at=rejected_at,
            last_error="Tool call rejected by user.",
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
        update(AgentToolCall)
        .where(
            AgentToolCall.id == tool_call_id,
            AgentToolCall.status.in_(
                ("pending", "awaiting_approval", "approved")
            ),
        )
        .values(
            status="rejected",
            last_error=reason,
            result_content=reason,
            result_summary=result_summary,
            result_is_error=True,
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
    updated = await db.execute(
        update(AgentToolCall)
        .where(
            AgentToolCall.id == tool_call_id,
            AgentToolCall.status.in_(("pending", "approved")),
            AgentToolCall.approved_by_user_id.is_(None),
        )
        .values(
            status="awaiting_approval",
            approval_required=True,
            policy_mode=policy_mode,
            updated_at=updated_at,
        )
    )
    return bool(updated.rowcount)


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
        .where(
            AgentRun.agent_id == agent_id,
            AgentRun.status.in_(AGENT_RUN_ACTIVE_STATUSES),
        )
        .limit(1)
    )
    if active_run is not None:
        return True
    legacy_call = await db.scalar(
        select(AgentToolCall.id)
        .join(AgentRun, AgentRun.id == AgentToolCall.run_id)
        .where(
            AgentRun.agent_id == agent_id,
            AgentToolCall.status.in_(
                ("pending", "approved", "running", "awaiting_approval")
            ),
        )
        .limit(1)
    )
    return legacy_call is not None


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
