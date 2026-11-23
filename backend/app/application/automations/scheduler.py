"""Scheduled trigger scanner, queue recovery, and notification reconciliation."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.application.automations.service import (
    _frozen_config_snapshot,
    dispatch_execution_by_id,
)
from app.application.notifications import (
    create_task_notification_in_txn,
    publish_live_task_notification,
)
from app.domain.agents.models import (
    AGENT_RUN_CANCELLED_STATUS,
    AGENT_RUN_FAILED_STATUS,
    AGENT_RUN_SUCCEEDED_STATUS,
    agent_run_display_status,
)

TERMINAL_RUN_STATUSES = frozenset(
    {
        AGENT_RUN_SUCCEEDED_STATUS,
        AGENT_RUN_FAILED_STATUS,
        AGENT_RUN_CANCELLED_STATUS,
    }
)
from app.domain.automations import (
    AUTOMATION_STATUS_ACTIVE,
    AUTOMATION_STATUS_COMPLETED,
    EXECUTION_DISPATCH_QUEUED,
    EXECUTION_DISPATCH_REJECTED,
    build_execution_input_snapshot,
    resolve_due_schedule_slot,
)
from app.entities.automations import AutomationExecution
from app.entities.defaults import utc_now
from app.infra.config.settings import Settings
from app.infra.db.repositories.agents import repository as agent_repository
from app.infra.db.repositories.automations import repository as automation_repository
from app.infra.db.repositories.identity import users as user_repository
from app.infra.db.repositories.tools import invocations as tool_repository
from app.infra.db.session import get_session_factory

logger = logging.getLogger(__name__)


async def _materialize_due_schedule_execution(
    automation_id: str,
    now_utc: datetime,
) -> str | None:
    async with get_session_factory()() as db:
        automation = await automation_repository.get_automation(
            db, automation_id, lock=True
        )
        if (
            automation is None
            or automation.status != AUTOMATION_STATUS_ACTIVE
            or automation.trigger_type not in {"once", "daily", "weekly"}
            or automation.next_run_at is None
        ):
            await db.rollback()
            return None

        due_at = (
            automation.next_run_at.replace(tzinfo=UTC)
            if automation.next_run_at.tzinfo is None
            else automation.next_run_at.astimezone(UTC)
        )
        if due_at > now_utc:
            await db.rollback()
            return None

        latest_slot_utc, missed_before, next_run_at = resolve_due_schedule_slot(
            automation.trigger_type,
            automation.trigger_config,
            due_at,
            now_utc,
        )
        dedup_key = (
            f"schedule:{automation.config_revision}:{latest_slot_utc.isoformat()}"
        )
        existing = await automation_repository.get_execution_by_dedup_key(
            db, automation.id, dedup_key
        )
        if existing is not None:
            if automation.trigger_type == "once":
                automation.status = AUTOMATION_STATUS_COMPLETED
                automation.next_run_at = None
            else:
                automation.next_run_at = next_run_at
            automation.updated_at = now_utc
            await automation_repository.save_automation(db, automation)
            await db.commit()
            return existing.id

        frozen_input = build_execution_input_snapshot(automation.input_config)
        execution = AutomationExecution(
            workspace_id=automation.workspace_id,
            automation_id=automation.id,
            owner_user_id=automation.owner_user_id,
            trigger_source="schedule",
            dedup_key=dedup_key,
            config_revision=automation.config_revision,
            scheduled_at=latest_slot_utc,
            received_at=now_utc,
            frozen_input=frozen_input,
            frozen_config=_frozen_config_snapshot(automation),
            dispatch_status=EXECUTION_DISPATCH_QUEUED,
            missed_count_before=missed_before,
            created_at=now_utc,
            updated_at=now_utc,
        )
        automation.missed_run_count += missed_before
        automation.last_triggered_at = now_utc
        automation.updated_at = now_utc
        if automation.trigger_type == "once":
            automation.status = AUTOMATION_STATUS_COMPLETED
            automation.next_run_at = None
        else:
            automation.next_run_at = next_run_at

        try:
            async with db.begin_nested():
                execution = await automation_repository.create_execution(db, execution)
                await automation_repository.save_automation(db, automation)
            await db.commit()
            return execution.id
        except IntegrityError:
            await db.rollback()
            fallback = await automation_repository.get_execution_by_dedup_key(
                db, automation.id, dedup_key
            )
            return fallback.id if fallback is not None else None


async def process_due_automations(
    settings: Settings,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Scan due Beat schedules once and dispatch at most the latest missed slot."""
    now_utc = (
        utc_now()
        if now is None
        else (now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC))
    )
    async with get_session_factory()() as db:
        due_ids = await automation_repository.list_due_automation_ids(db, now_utc)
    execution_ids: list[str] = []
    for automation_id in due_ids:
        exec_id = await _materialize_due_schedule_execution(automation_id, now_utc)
        if exec_id is not None:
            execution_ids.append(exec_id)
            await dispatch_execution_by_id(exec_id, settings)
    return execution_ids


async def recover_pending_automation_executions(settings: Settings) -> list[str]:
    """Recover pending Run dispatches and drain queued webhook executions serially."""
    async with get_session_factory()() as db:
        execution_ids = await automation_repository.list_recoverable_execution_ids(db)
    recovered: list[str] = []
    for execution_id in execution_ids:
        try:
            result = await dispatch_execution_by_id(execution_id, settings)
        except Exception:
            logger.exception("Automation dispatch recovery failed: %s", execution_id)
            continue
        if result is not None:
            recovered.append(execution_id)
    return recovered


async def _wait_token_for_run(db, run) -> str:
    display = agent_run_display_status(run.status)
    step = (run.checkpoint or {}).get("workflow_engine", {}).get("step_count", 0)
    if display == "awaiting_input":
        form = (run.checkpoint or {}).get("workflow_form")
        node_id = form.get("runtime_node_id") if isinstance(form, dict) else None
        if node_id:
            return "form:" + hashlib.sha256(f"{node_id}:{step}".encode()).hexdigest()
        return f"input:{step}"
    if display == "awaiting_approval":
        invocations = await tool_repository.list_tool_invocations(
            db, run.workspace_id, run.id
        )
        pending_ids = sorted(
            item.id
            for item in invocations
            if item.status in {"awaiting_approval", "uncertain"}
        )
        if pending_ids:
            return (
                "approval:" + hashlib.sha256(",".join(pending_ids).encode()).hexdigest()
            )
        return "approval"
    return display


async def reconcile_automation_notifications(settings: Settings) -> int:
    """Reconcile unclosed root automation executions into deduplicated user notifications."""
    async with get_session_factory()() as db:
        unclosed = await automation_repository.list_unclosed_notification_executions(db)

    created_count = 0
    for execution_row, _automation in unclosed:
        created_notification = None
        async with get_session_factory()() as db:
            execution = await automation_repository.get_execution(
                db, execution_row.id, lock=True
            )
            if execution is None or execution.notification_closed:
                await db.rollback()
                continue
            recipient = await user_repository.get_user_by_id(
                db, execution.owner_user_id
            )
            if recipient is None or not recipient.is_active:
                execution.notification_closed = True
                execution.updated_at = utc_now()
                await automation_repository.save_execution(db, execution)
                await db.commit()
                continue
            run = (
                await agent_repository.get_agent_run_by_id(db, execution.run_id)
                if execution.run_id
                else None
            )
            if run is None and (
                execution.dispatch_status == EXECUTION_DISPATCH_REJECTED
                or execution.last_reconciled_run_status == "cancelled"
            ):
                frozen = execution.frozen_config or {}
                prefs = frozen.get("notification_config", {})
                event_type = (
                    "cancelled"
                    if execution.last_reconciled_run_status == "cancelled"
                    else "failed"
                )
                if prefs.get(f"on_{event_type}", True):
                    notification, created = await create_task_notification_in_txn(
                        db,
                        user_id=execution.owner_user_id,
                        workspace_id=execution.workspace_id,
                        automation_id=execution.automation_id,
                        execution_id=execution.id,
                        automation_name=str(frozen.get("name") or "Automation"),
                        run_id=None,
                        event_type=event_type,
                        dedup_key=f"exec:{execution.id}:{event_type}",
                        target_app_id=frozen.get("target_app_id"),
                        target_app_type=frozen.get("target_app_type"),
                        trigger_source=execution.trigger_source,
                    )
                    if created:
                        created_notification = notification
                        created_count += 1
                execution.notification_closed = True
                execution.updated_at = utc_now()
                await automation_repository.save_execution(db, execution)
                await db.commit()
                if created_notification is not None:
                    await publish_live_task_notification(settings, created_notification)
                continue
            if run is None:
                execution.notification_closed = True
                execution.updated_at = utc_now()
                await automation_repository.save_execution(db, execution)
                await db.commit()
                continue
            # Notify strictly on root runs, never child agent runs spawned inside workflows.
            if run.depth != 0 or run.parent_run_id is not None:
                execution.notification_closed = True
                execution.updated_at = utc_now()
                await automation_repository.save_execution(db, execution)
                await db.commit()
                continue

            automation = await automation_repository.get_automation(
                db, execution.automation_id
            )
            automation_name = (
                automation.name
                if automation is not None
                else str(
                    (execution.frozen_config or {}).get("target_app_id", "Automation")
                )
            )
            prefs = (
                dict(
                    (execution.frozen_config or {}).get(
                        "notification_config", automation.notification_config
                    )
                    or {}
                )
                if automation is not None
                else {
                    "on_succeeded": True,
                    "on_failed": True,
                    "on_cancelled": True,
                    "on_awaiting_approval": True,
                    "on_awaiting_input": True,
                }
            )
            display = agent_run_display_status(run.status)
            state_marker = await _wait_token_for_run(db, run)

            if run.status in TERMINAL_RUN_STATUSES:
                event_type = display
                if prefs.get(f"on_{event_type}", True):
                    notification, created = await create_task_notification_in_txn(
                        db,
                        user_id=execution.owner_user_id,
                        workspace_id=execution.workspace_id,
                        automation_id=execution.automation_id,
                        automation_name=automation_name,
                        execution_id=execution.id,
                        run_id=run.id,
                        event_type=event_type,
                        dedup_key=f"exec:{execution.id}:{event_type}",
                        target_app_id=(execution.frozen_config or {}).get(
                            "target_app_id"
                        ),
                        target_app_type=(execution.frozen_config or {}).get(
                            "target_app_type"
                        ),
                        trigger_source=execution.trigger_source,
                    )
                    if created:
                        created_notification = notification
                        created_count += 1
                execution.last_reconciled_run_status = state_marker
                execution.notification_closed = True
                execution.updated_at = utc_now()
                await automation_repository.save_execution(db, execution)
                await db.commit()

            elif display in {"awaiting_approval", "awaiting_input"}:
                if execution.last_reconciled_run_status != state_marker:
                    if prefs.get(f"on_{display}", True):
                        notification, created = await create_task_notification_in_txn(
                            db,
                            user_id=execution.owner_user_id,
                            workspace_id=execution.workspace_id,
                            automation_id=execution.automation_id,
                            automation_name=automation_name,
                            execution_id=execution.id,
                            run_id=run.id,
                            event_type=display,
                            dedup_key=f"exec:{execution.id}:{state_marker}",
                            target_app_id=(execution.frozen_config or {}).get(
                                "target_app_id"
                            ),
                            target_app_type=(execution.frozen_config or {}).get(
                                "target_app_type"
                            ),
                            trigger_source=execution.trigger_source,
                        )
                        if created:
                            created_notification = notification
                            created_count += 1
                    execution.last_reconciled_run_status = state_marker
                    execution.updated_at = utc_now()
                    await automation_repository.save_execution(db, execution)
                    await db.commit()
                else:
                    execution.updated_at = utc_now()
                    await automation_repository.save_execution(db, execution)
                    await db.commit()
            else:
                if execution.last_reconciled_run_status != state_marker:
                    execution.last_reconciled_run_status = state_marker
                    execution.updated_at = utc_now()
                    await automation_repository.save_execution(db, execution)
                    await db.commit()
                else:
                    execution.updated_at = utc_now()
                    await automation_repository.save_execution(db, execution)
                    await db.commit()

        if created_notification is not None:
            await publish_live_task_notification(settings, created_notification)

    return created_count


async def run_automation_maintenance(settings: Settings) -> None:
    """Periodic maintenance step invoked by Celery Beat."""
    await reconcile_automation_notifications(settings)
    await process_due_automations(settings)
    await recover_pending_automation_executions(settings)
