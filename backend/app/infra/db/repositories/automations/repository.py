"""SQLAlchemy repository functions for automations and automation executions."""

from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.agents.models import AGENT_RUN_ACTIVE_STATUSES, AgentRunState
from app.domain.automations.models import (
    AUTOMATION_STATUS_ACTIVE,
    EXECUTION_DISPATCH_PENDING,
    EXECUTION_DISPATCH_QUEUED,
    EXECUTION_DISPATCH_REJECTED,
)
from app.domain.automations.models import (
    Automation as AutomationOrm,
)
from app.domain.automations.models import (
    AutomationExecution as AutomationExecutionOrm,
)
from app.entities.automations import Automation, AutomationExecution
from app.infra.db import mapping


async def create_automation(
    db: AsyncSession,
    entity: Automation,
) -> Automation:
    row = await mapping.save(db, AutomationOrm, entity)
    return mapping.to_entity(Automation, row)


async def save_automation(
    db: AsyncSession,
    entity: Automation,
) -> Automation:
    row = await mapping.save(db, AutomationOrm, entity)
    return mapping.to_entity(Automation, row)


async def get_automation(
    db: AsyncSession,
    automation_id: str,
    *,
    lock: bool = False,
) -> Automation | None:
    statement = select(AutomationOrm).where(AutomationOrm.id == automation_id)
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    return mapping.to_entity(Automation, row) if row is not None else None


async def get_workspace_automation(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    *,
    lock: bool = False,
) -> Automation | None:
    statement = select(AutomationOrm).where(
        AutomationOrm.workspace_id == workspace_id,
        AutomationOrm.id == automation_id,
    )
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    return mapping.to_entity(Automation, row) if row is not None else None


async def get_automation_by_hook_id(
    db: AsyncSession,
    hook_id: str,
    *,
    lock: bool = False,
) -> Automation | None:
    statement = select(AutomationOrm).where(AutomationOrm.webhook_hook_id == hook_id)
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    return mapping.to_entity(Automation, row) if row is not None else None


async def list_automations_for_owner(
    db: AsyncSession,
    workspace_id: str,
    owner_user_id: str,
    *,
    target_app_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Automation], int]:
    filters = [
        AutomationOrm.workspace_id == workspace_id,
        AutomationOrm.owner_user_id == owner_user_id,
    ]
    if target_app_id is not None:
        filters.append(AutomationOrm.target_app_id == target_app_id)
    total = int(
        await db.scalar(select(func.count(AutomationOrm.id)).where(*filters)) or 0
    )
    rows = await db.scalars(
        select(AutomationOrm)
        .where(*filters)
        .order_by(AutomationOrm.created_at.desc(), AutomationOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return ([mapping.to_entity(Automation, row) for row in rows.all()], total)


async def list_due_automation_ids(
    db: AsyncSession,
    now: datetime,
    *,
    limit: int = 50,
) -> list[str]:
    rows = await db.scalars(
        select(AutomationOrm.id)
        .where(
            AutomationOrm.status == AUTOMATION_STATUS_ACTIVE,
            AutomationOrm.trigger_type.in_(("once", "daily", "weekly")),
            AutomationOrm.next_run_at.is_not(None),
            AutomationOrm.next_run_at <= now,
        )
        .order_by(AutomationOrm.next_run_at.asc(), AutomationOrm.id.asc())
        .limit(limit)
    )
    return list(rows.all())


async def create_execution(
    db: AsyncSession,
    entity: AutomationExecution,
) -> AutomationExecution:
    row = await mapping.save(db, AutomationExecutionOrm, entity)
    return mapping.to_entity(AutomationExecution, row)


async def save_execution(
    db: AsyncSession,
    entity: AutomationExecution,
) -> AutomationExecution:
    row = await mapping.save(db, AutomationExecutionOrm, entity)
    return mapping.to_entity(AutomationExecution, row)


async def get_execution(
    db: AsyncSession,
    execution_id: str,
    *,
    lock: bool = False,
) -> AutomationExecution | None:
    statement = select(AutomationExecutionOrm).where(
        AutomationExecutionOrm.id == execution_id
    )
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    return mapping.to_entity(AutomationExecution, row) if row is not None else None


async def get_execution_for_automation(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    execution_id: str,
    *,
    lock: bool = False,
) -> AutomationExecution | None:
    statement = select(AutomationExecutionOrm).where(
        AutomationExecutionOrm.workspace_id == workspace_id,
        AutomationExecutionOrm.automation_id == automation_id,
        AutomationExecutionOrm.id == execution_id,
    )
    if lock:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    return mapping.to_entity(AutomationExecution, row) if row is not None else None


async def get_execution_by_dedup_key(
    db: AsyncSession,
    automation_id: str,
    dedup_key: str,
) -> AutomationExecution | None:
    row = await db.scalar(
        select(AutomationExecutionOrm).where(
            AutomationExecutionOrm.automation_id == automation_id,
            AutomationExecutionOrm.dedup_key == dedup_key,
        )
    )
    return mapping.to_entity(AutomationExecution, row) if row is not None else None


async def list_executions_for_automation(
    db: AsyncSession,
    workspace_id: str,
    automation_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AutomationExecution], int]:
    filters = (
        AutomationExecutionOrm.workspace_id == workspace_id,
        AutomationExecutionOrm.automation_id == automation_id,
    )
    total = int(
        await db.scalar(select(func.count(AutomationExecutionOrm.id)).where(*filters))
        or 0
    )
    rows = await db.scalars(
        select(AutomationExecutionOrm)
        .where(*filters)
        .order_by(
            AutomationExecutionOrm.created_at.desc(),
            AutomationExecutionOrm.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return ([mapping.to_entity(AutomationExecution, row) for row in rows.all()], total)


async def list_latest_executions_by_automation_ids(
    db: AsyncSession,
    automation_ids: list[str],
) -> dict[str, AutomationExecution]:
    if not automation_ids:
        return {}
    ranked = (
        select(
            AutomationExecutionOrm.id.label("execution_id"),
            func.row_number()
            .over(
                partition_by=AutomationExecutionOrm.automation_id,
                order_by=(
                    AutomationExecutionOrm.created_at.desc(),
                    AutomationExecutionOrm.id.desc(),
                ),
            )
            .label("row_num"),
        )
        .where(AutomationExecutionOrm.automation_id.in_(automation_ids))
        .subquery()
    )
    rows = await db.scalars(
        select(AutomationExecutionOrm)
        .join(ranked, ranked.c.execution_id == AutomationExecutionOrm.id)
        .where(ranked.c.row_num == 1)
    )
    items = [mapping.to_entity(AutomationExecution, row) for row in rows.all()]
    return {item.automation_id: item for item in items}


async def count_pending_webhook_executions(
    db: AsyncSession,
    automation_id: str,
) -> int:
    value = await db.scalar(
        select(func.count(AutomationExecutionOrm.id)).where(
            AutomationExecutionOrm.automation_id == automation_id,
            AutomationExecutionOrm.trigger_source == "webhook",
            AutomationExecutionOrm.dispatch_status.in_(
                (EXECUTION_DISPATCH_QUEUED, EXECUTION_DISPATCH_PENDING)
            ),
        )
    )
    return int(value or 0)


async def has_active_execution_or_run(
    db: AsyncSession,
    automation_id: str,
    *,
    exclude_execution_id: str | None = None,
) -> bool:
    statement = (
        select(AutomationExecutionOrm.id)
        .outerjoin(
            AgentRunState,
            AgentRunState.run_id == AutomationExecutionOrm.run_id,
        )
        .where(
            AutomationExecutionOrm.automation_id == automation_id,
            or_(
                AutomationExecutionOrm.dispatch_status == EXECUTION_DISPATCH_PENDING,
                AgentRunState.status.in_(AGENT_RUN_ACTIVE_STATUSES),
            ),
        )
        .limit(1)
    )
    if exclude_execution_id is not None:
        statement = statement.where(AutomationExecutionOrm.id != exclude_execution_id)
    return (await db.scalar(statement)) is not None


async def get_next_queued_execution_id(
    db: AsyncSession,
    automation_id: str,
) -> str | None:
    return await db.scalar(
        select(AutomationExecutionOrm.id)
        .where(
            AutomationExecutionOrm.automation_id == automation_id,
            AutomationExecutionOrm.dispatch_status == EXECUTION_DISPATCH_QUEUED,
        )
        .order_by(
            AutomationExecutionOrm.received_at.asc(),
            AutomationExecutionOrm.id.asc(),
        )
        .limit(1)
    )


async def list_recoverable_execution_ids(
    db: AsyncSession,
    *,
    limit: int = 50,
) -> list[str]:
    queued = (
        select(
            AutomationExecutionOrm.id.label("execution_id"),
            func.row_number()
            .over(
                partition_by=AutomationExecutionOrm.automation_id,
                order_by=(
                    AutomationExecutionOrm.received_at,
                    AutomationExecutionOrm.id,
                ),
            )
            .label("position"),
        )
        .where(AutomationExecutionOrm.dispatch_status == EXECUTION_DISPATCH_QUEUED)
        .subquery()
    )
    other = aliased(AutomationExecutionOrm)
    active = (
        select(other.id)
        .outerjoin(
            AgentRunState,
            AgentRunState.run_id == other.run_id,
        )
        .where(
            other.automation_id == AutomationOrm.id,
            or_(
                other.dispatch_status == EXECUTION_DISPATCH_PENDING,
                AgentRunState.status.in_(AGENT_RUN_ACTIVE_STATUSES),
            ),
        )
        .correlate(AutomationOrm)
        .exists()
    )
    rows = await db.scalars(
        select(AutomationExecutionOrm.id)
        .join(AutomationOrm, AutomationOrm.id == AutomationExecutionOrm.automation_id)
        .outerjoin(queued, queued.c.execution_id == AutomationExecutionOrm.id)
        .where(
            AutomationOrm.status != "paused",
            or_(
                AutomationExecutionOrm.dispatch_status == EXECUTION_DISPATCH_PENDING,
                and_(queued.c.position == 1, ~active),
            ),
        )
        .order_by(AutomationExecutionOrm.updated_at, AutomationExecutionOrm.id)
        .limit(limit)
    )
    return list(rows.all())


async def list_unclosed_notification_executions(
    db: AsyncSession,
    *,
    limit: int = 100,
) -> list[tuple[AutomationExecution, Automation | None]]:
    rows = (
        await db.execute(
            select(AutomationExecutionOrm, AutomationOrm)
            .outerjoin(
                AutomationOrm,
                AutomationOrm.id == AutomationExecutionOrm.automation_id,
            )
            .where(
                AutomationExecutionOrm.notification_closed.is_(False),
                or_(
                    AutomationExecutionOrm.run_id.is_not(None),
                    AutomationExecutionOrm.dispatch_status
                    == EXECUTION_DISPATCH_REJECTED,
                    AutomationExecutionOrm.last_reconciled_run_status == "cancelled",
                ),
            )
            .order_by(
                AutomationExecutionOrm.updated_at.asc(),
                AutomationExecutionOrm.id.asc(),
            )
            .limit(limit)
        )
    ).all()
    return [
        (
            mapping.to_entity(AutomationExecution, execution_row),
            mapping.to_entity(Automation, automation_row)
            if automation_row is not None
            else None,
        )
        for execution_row, automation_row in rows
    ]


async def delete_automations_for_agent(
    db: AsyncSession,
    agent_id: str,
) -> None:
    automation_ids = select(AutomationOrm.id).where(
        AutomationOrm.target_app_id == agent_id
    )
    await db.execute(
        delete(AutomationExecutionOrm).where(
            AutomationExecutionOrm.automation_id.in_(automation_ids)
        )
    )
    await db.execute(
        delete(AutomationOrm).where(AutomationOrm.target_app_id == agent_id)
    )


async def delete_automations_for_workspace(
    db: AsyncSession,
    workspace_id: str,
) -> None:
    await db.execute(
        delete(AutomationExecutionOrm).where(
            AutomationExecutionOrm.workspace_id == workspace_id
        )
    )
    await db.execute(
        delete(AutomationOrm).where(AutomationOrm.workspace_id == workspace_id)
    )


async def disable_automations_for_user(db: AsyncSession, user_id: str) -> None:
    """Remove departed account credentials while preserving execution history."""
    await db.execute(
        update(AutomationExecutionOrm)
        .where(
            AutomationExecutionOrm.owner_user_id == user_id,
            AutomationExecutionOrm.dispatch_status.in_(
                (EXECUTION_DISPATCH_QUEUED, EXECUTION_DISPATCH_PENDING)
            ),
        )
        .values(
            dispatch_status=EXECUTION_DISPATCH_REJECTED,
            skip_reason="Automation owner user is inactive or missing.",
            notification_closed=True,
        )
    )
    await db.execute(
        update(AutomationOrm)
        .where(AutomationOrm.owner_user_id == user_id)
        .values(
            status="paused",
            next_run_at=None,
            webhook_secret_ciphertext=None,
            webhook_secret_hint=None,
            webhook_secret_updated_at=None,
        )
    )
