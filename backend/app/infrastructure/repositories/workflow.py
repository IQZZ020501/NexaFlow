from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.workflows import (
    WorkflowDefinition as WorkflowDefinitionEntity,
    WorkflowNodeExecution as WorkflowNodeExecutionEntity,
    WorkflowRunDetail as WorkflowRunDetailEntity,
    WorkflowVersion as WorkflowVersionEntity,
    WorkflowUpload as WorkflowUploadEntity,
    WorkflowUploadStorageCleanup as WorkflowUploadStorageCleanupEntity,
)
from app.infrastructure.repositories.mapping import refresh_entity, save, to_entity, to_orm
from app.infrastructure.model_utils import utc_now
from app.shareddomain.agents.models import Agent, AgentRun
from app.shareddomain.workflows.models import (
    WorkflowDefinition,
    WorkflowNodeExecution,
    WorkflowRunDetail,
    WorkflowVersion,
    WorkflowUpload,
    WorkflowUploadStorageCleanup,
)


async def create_upload(
    db: AsyncSession,
    entity: WorkflowUploadEntity,
) -> WorkflowUploadEntity:
    row = await save(db, WorkflowUpload, entity)
    return to_entity(WorkflowUploadEntity, row)


async def list_uploads(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    uploaded_by_user_id: str,
    upload_ids: list[str],
) -> list[WorkflowUploadEntity]:
    if not upload_ids:
        return []
    rows = await db.scalars(
        select(WorkflowUpload).where(
            WorkflowUpload.workspace_id == workspace_id,
            WorkflowUpload.agent_id == agent_id,
            WorkflowUpload.uploaded_by_user_id == uploaded_by_user_id,
            WorkflowUpload.id.in_(upload_ids),
            WorkflowUpload.expires_at > utc_now(),
        ).with_for_update()
    )
    return [to_entity(WorkflowUploadEntity, row) for row in rows.all()]


async def lock_upload_application(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
) -> bool:
    locked_agent_id = await db.scalar(
        select(Agent.id)
        .where(Agent.workspace_id == workspace_id, Agent.id == agent_id)
        .with_for_update()
    )
    return locked_agent_id is not None


async def queue_upload_cleanups(
    db: AsyncSession,
    *,
    upload_ids: list[str] | None = None,
    agent_id: str | None = None,
    workspace_id: str | None = None,
    uploaded_by_user_id: str | None = None,
    expired_at: datetime | None = None,
) -> list[str]:
    conditions = []
    if upload_ids is not None:
        if not upload_ids:
            return []
        conditions.append(WorkflowUpload.id.in_(upload_ids))
    if agent_id is not None:
        conditions.append(WorkflowUpload.agent_id == agent_id)
    if workspace_id is not None:
        conditions.append(WorkflowUpload.workspace_id == workspace_id)
    if uploaded_by_user_id is not None:
        conditions.append(WorkflowUpload.uploaded_by_user_id == uploaded_by_user_id)
    if expired_at is not None:
        conditions.append(WorkflowUpload.expires_at <= expired_at)
    if not conditions:
        raise ValueError("Workflow upload cleanup requires a target.")

    uploads = list(
        (
            await db.scalars(
                select(WorkflowUpload).where(*conditions).with_for_update()
            )
        ).all()
    )
    cleanups = [
        WorkflowUploadStorageCleanupEntity(
            workspace_id=upload.workspace_id,
            uploaded_by_user_id=upload.uploaded_by_user_id,
            object_key=upload.object_key,
            size_bytes=upload.size_bytes,
        )
        for upload in uploads
    ]
    if cleanups:
        db.add_all(
            [
                to_orm(WorkflowUploadStorageCleanup, cleanup)
                for cleanup in cleanups
            ]
        )
        await db.flush()
    if uploads:
        await db.execute(
            delete(WorkflowUpload).where(
                WorkflowUpload.id.in_([upload.id for upload in uploads])
            )
        )
    return [cleanup.id for cleanup in cleanups]


async def create_upload_cleanup(
    db: AsyncSession,
    entity: WorkflowUploadStorageCleanupEntity,
) -> WorkflowUploadStorageCleanupEntity:
    row = await save(db, WorkflowUploadStorageCleanup, entity)
    return to_entity(WorkflowUploadStorageCleanupEntity, row)


async def lock_upload_cleanup(
    db: AsyncSession,
    cleanup_id: str,
) -> WorkflowUploadStorageCleanupEntity | None:
    row = await db.scalar(
        select(WorkflowUploadStorageCleanup)
        .where(WorkflowUploadStorageCleanup.id == cleanup_id)
        .with_for_update()
    )
    return (
        to_entity(WorkflowUploadStorageCleanupEntity, row)
        if row is not None
        else None
    )


async def list_due_upload_cleanup_ids(
    db: AsyncSession,
    due_at: datetime,
    limit: int,
) -> list[str]:
    rows = await db.scalars(
        select(WorkflowUploadStorageCleanup.id)
        .where(WorkflowUploadStorageCleanup.next_attempt_at <= due_at)
        .order_by(
            WorkflowUploadStorageCleanup.next_attempt_at,
            WorkflowUploadStorageCleanup.id,
        )
        .limit(limit)
    )
    return list(rows.all())


async def has_upload_cleanup_for_object(db: AsyncSession, object_key: str) -> bool:
    return (
        await db.scalar(
            select(WorkflowUploadStorageCleanup.id).where(
                WorkflowUploadStorageCleanup.object_key == object_key
            )
        )
        is not None
    )


async def save_upload_cleanup(
    db: AsyncSession,
    entity: WorkflowUploadStorageCleanupEntity,
) -> None:
    await save(db, WorkflowUploadStorageCleanup, entity)


async def delete_upload_cleanup(db: AsyncSession, cleanup_id: str) -> None:
    await db.execute(
        delete(WorkflowUploadStorageCleanup).where(
            WorkflowUploadStorageCleanup.id == cleanup_id
        )
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
            updated_at=utc_now(),
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


async def set_first_run_deadline(
    db: AsyncSession,
    run_id: str,
    worker_task_id: str,
    deadline_at: datetime,
) -> None:
    await db.execute(
        update(WorkflowRunDetail)
        .where(
            WorkflowRunDetail.run_id == run_id,
            select(AgentRun.attempts)
            .where(
                AgentRun.id == run_id,
                AgentRun.worker_task_id == worker_task_id,
            )
            .scalar_subquery()
            == 1,
        )
        .values(deadline_at=deadline_at, updated_at=utc_now())
    )


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
            updated_at=utc_now(),
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
