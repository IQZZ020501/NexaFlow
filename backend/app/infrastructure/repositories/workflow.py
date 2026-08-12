from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.workflows import (
    WorkflowDefinition as WorkflowDefinitionEntity,
    WorkflowNodeExecution as WorkflowNodeExecutionEntity,
    WorkflowRunDetail as WorkflowRunDetailEntity,
    WorkflowVersion as WorkflowVersionEntity,
)
from app.infrastructure.repositories.mapping import refresh_entity, save, to_entity
from app.shareddomain.agents.models import AgentRun
from app.shareddomain.workflows.models import (
    WorkflowDefinition,
    WorkflowNodeExecution,
    WorkflowRunDetail,
    WorkflowVersion,
)


async def get_definition(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
) -> WorkflowDefinitionEntity | None:
    row = await db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.workspace_id == workspace_id,
            WorkflowDefinition.agent_id == agent_id,
        )
    )
    return to_entity(WorkflowDefinitionEntity, row) if row is not None else None


async def lock_definition(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
) -> WorkflowDefinitionEntity | None:
    row = await db.scalar(
        select(WorkflowDefinition)
        .where(
            WorkflowDefinition.workspace_id == workspace_id,
            WorkflowDefinition.agent_id == agent_id,
        )
        .with_for_update()
    )
    return to_entity(WorkflowDefinitionEntity, row) if row is not None else None


async def create_definition(
    db: AsyncSession,
    entity: WorkflowDefinitionEntity,
) -> WorkflowDefinitionEntity:
    row = await save(db, WorkflowDefinition, entity)
    return to_entity(WorkflowDefinitionEntity, row)


async def update_definition_graph(
    db: AsyncSession,
    definition_id: str,
    expected_revision: int,
    graph: dict,
    graph_hash: str,
    updated_by_user_id: str,
) -> WorkflowDefinitionEntity | None:
    row = await db.scalar(
        update(WorkflowDefinition)
        .where(
            WorkflowDefinition.id == definition_id,
            WorkflowDefinition.revision == expected_revision,
        )
        .values(
            revision=WorkflowDefinition.revision + 1,
            graph=graph,
            graph_hash=graph_hash,
            updated_by_user_id=updated_by_user_id,
            updated_at=func.now(),
        )
        .returning(WorkflowDefinition)
    )
    return to_entity(WorkflowDefinitionEntity, row) if row is not None else None


async def refresh_definition(
    db: AsyncSession,
    entity: WorkflowDefinitionEntity,
) -> WorkflowDefinitionEntity:
    return await refresh_entity(db, WorkflowDefinition, WorkflowDefinitionEntity, entity)


async def create_version(
    db: AsyncSession,
    entity: WorkflowVersionEntity,
) -> WorkflowVersionEntity:
    row = await save(db, WorkflowVersion, entity)
    return to_entity(WorkflowVersionEntity, row)


async def next_version_number(db: AsyncSession, agent_id: str) -> int:
    value = await db.scalar(
        select(func.max(WorkflowVersion.version_number)).where(
            WorkflowVersion.agent_id == agent_id
        )
    )
    return int(value or 0) + 1


async def list_versions(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
) -> list[WorkflowVersionEntity]:
    rows = await db.scalars(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.workspace_id == workspace_id,
            WorkflowVersion.agent_id == agent_id,
        )
        .order_by(WorkflowVersion.version_number.desc())
    )
    return [to_entity(WorkflowVersionEntity, row) for row in rows.all()]


async def get_version(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    version_number: int | None = None,
) -> WorkflowVersionEntity | None:
    statement = select(WorkflowVersion).where(
        WorkflowVersion.workspace_id == workspace_id,
        WorkflowVersion.agent_id == agent_id,
    )
    if version_number is not None:
        statement = statement.where(WorkflowVersion.version_number == version_number)
    row = await db.scalar(statement.order_by(WorkflowVersion.version_number.desc()).limit(1))
    return to_entity(WorkflowVersionEntity, row) if row is not None else None


async def create_run_detail(
    db: AsyncSession,
    entity: WorkflowRunDetailEntity,
) -> WorkflowRunDetailEntity:
    row = await save(db, WorkflowRunDetail, entity)
    return to_entity(WorkflowRunDetailEntity, row)


async def get_run_detail(
    db: AsyncSession,
    run_id: str,
) -> WorkflowRunDetailEntity | None:
    row = await db.scalar(
        select(WorkflowRunDetail).where(WorkflowRunDetail.run_id == run_id)
    )
    return to_entity(WorkflowRunDetailEntity, row) if row is not None else None


async def save_owned_run_detail(
    db: AsyncSession,
    entity: WorkflowRunDetailEntity,
    worker_task_id: str,
) -> bool:
    owned = await db.scalar(
        select(AgentRun.id).where(
            AgentRun.id == entity.run_id,
            AgentRun.status == "running",
            AgentRun.worker_task_id == worker_task_id,
        )
    )
    if owned is None:
        return False
    result = await db.execute(
        update(WorkflowRunDetail)
        .where(WorkflowRunDetail.id == entity.id)
        .values(
            outputs=entity.outputs,
            step_count=entity.step_count,
            token_usage=entity.token_usage,
            updated_at=func.now(),
        )
    )
    return bool(result.rowcount)


async def start_node_execution(
    db: AsyncSession,
    *,
    workspace_id: str,
    run_id: str,
    worker_task_id: str,
    node_id: str,
    node_type: str,
    sequence: int,
    started_at: datetime,
) -> WorkflowNodeExecutionEntity | None:
    owned = await db.scalar(
        select(AgentRun.id).where(
            AgentRun.id == run_id,
            AgentRun.status == "running",
            AgentRun.worker_task_id == worker_task_id,
        )
    )
    if owned is None:
        return None
    row = await db.scalar(
        select(WorkflowNodeExecution).where(
            WorkflowNodeExecution.run_id == run_id,
            WorkflowNodeExecution.node_id == node_id,
        )
    )
    if row is None:
        row = WorkflowNodeExecution(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            node_type=node_type,
            status="running",
            sequence=sequence,
            inputs={},
            outputs={},
            model_usage={},
            started_at=started_at,
        )
        db.add(row)
    else:
        row.node_type = node_type
        row.status = "running"
        row.sequence = sequence
        row.inputs = {}
        row.outputs = {}
        row.model_usage = {}
        row.error = None
        row.started_at = started_at
        row.finished_at = None
        row.duration_ms = None
        row.updated_at = started_at
    await db.flush()
    return to_entity(WorkflowNodeExecutionEntity, row)


async def finish_node_execution(
    db: AsyncSession,
    entity: WorkflowNodeExecutionEntity,
    worker_task_id: str,
) -> bool:
    owned = await db.scalar(
        select(AgentRun.id).where(
            AgentRun.id == entity.run_id,
            AgentRun.status == "running",
            AgentRun.worker_task_id == worker_task_id,
        )
    )
    if owned is None:
        return False
    result = await db.execute(
        update(WorkflowNodeExecution)
        .where(WorkflowNodeExecution.id == entity.id)
        .values(
            status=entity.status,
            sequence=entity.sequence,
            inputs=entity.inputs,
            outputs=entity.outputs,
            model_usage=entity.model_usage,
            error=entity.error,
            started_at=entity.started_at,
            finished_at=entity.finished_at,
            duration_ms=entity.duration_ms,
            updated_at=entity.updated_at,
        )
    )
    return bool(result.rowcount)


async def list_node_executions(
    db: AsyncSession,
    run_id: str,
) -> list[WorkflowNodeExecutionEntity]:
    rows = await db.scalars(
        select(WorkflowNodeExecution)
        .where(WorkflowNodeExecution.run_id == run_id)
        .order_by(WorkflowNodeExecution.sequence, WorkflowNodeExecution.node_id)
    )
    return [to_entity(WorkflowNodeExecutionEntity, row) for row in rows.all()]


async def list_run_details_for_external_conversations(
    db: AsyncSession,
    run_ids: list[str],
) -> list[WorkflowRunDetailEntity]:
    if not run_ids:
        return []
    rows = await db.scalars(
        select(WorkflowRunDetail).where(WorkflowRunDetail.run_id.in_(run_ids))
    )
    return [to_entity(WorkflowRunDetailEntity, row) for row in rows.all()]
