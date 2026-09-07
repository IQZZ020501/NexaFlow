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
    from app.infra.db.repositories.tools import repository as tool_repository

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
    from app.infra.db.repositories.tools import repository as tool_repository

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

