"""Periodic recovery orchestration behind one Celery task interface."""

from collections.abc import Callable

from app.application.agents.runs.children import reconcile_workflow_agent_children
from app.application.agents.runs.executor import (
    list_recoverable_legacy_agent_run_ids,
    list_recoverable_unified_agent_run_ids,
)
from app.application.artifacts.service import cleanup_expired_generated_artifacts
from app.application.email.delivery import list_due_email_delivery_ids
from app.application.knowledge.graph.maintenance import reconcile_knowledge_graphs
from app.application.tools.runtime.service import (
    list_recoverable_tool_test_invocation_ids,
)
from app.domain.knowledge.storage.cleanup import (
    list_due_knowledge_storage_cleanup_ids,
)
from app.domain.knowledge.tasks.runner import list_recoverable_knowledge_task_ids
from app.domain.workflows.uploads import prepare_due_upload_cleanups
from app.infra.config.settings import Settings
from app.infra.observability.errors import log_error
from app.infra.observability.logger import get_logger
from app.infra.queue.celery import celery_app
from app.tasks.agents.jobs import run_agent_job
from app.tasks.email.jobs import run_email_delivery_job
from app.tasks.knowledge.jobs import run_knowledge_task_job
from app.tasks.runtime import configure_task_worker, run_task_async
from app.tasks.storage.jobs import run_storage_cleanup_job
from app.tasks.tools.jobs import run_tool_invocation_job

logger = get_logger(__name__)

MaintenanceStep = tuple[str, Callable[[Settings], None]]


def _recover_knowledge_tasks(settings: Settings) -> None:
    task_ids = run_task_async(list_recoverable_knowledge_task_ids(settings))
    for task_id in task_ids:
        run_knowledge_task_job.apply_async(args=(task_id,))


def _recover_unified_agent_runs(settings: Settings) -> None:
    run_task_async(reconcile_workflow_agent_children())
    run_ids = run_task_async(list_recoverable_unified_agent_run_ids(settings))
    for run_id in run_ids:
        run_agent_job.apply_async(
            args=(run_id, "unified"),
            queue="agents-v2",
        )


def _recover_legacy_agent_runs(settings: Settings) -> None:
    run_ids = run_task_async(list_recoverable_legacy_agent_run_ids(settings))
    for run_id in run_ids:
        run_agent_job.apply_async(
            args=(run_id, "legacy"),
            queue="agents-legacy",
        )


def _recover_tool_invocations(_settings: Settings) -> None:
    invocation_ids = run_task_async(list_recoverable_tool_test_invocation_ids())
    for invocation_id in invocation_ids:
        run_tool_invocation_job.apply_async(args=(invocation_id,))


def _recover_email_deliveries(_settings: Settings) -> None:
    delivery_ids = run_task_async(list_due_email_delivery_ids())
    for delivery_id in delivery_ids:
        run_email_delivery_job.apply_async(args=(delivery_id,))


def _cleanup_expired_artifacts(_settings: Settings) -> None:
    run_task_async(cleanup_expired_generated_artifacts())


def _reconcile_knowledge_graphs(settings: Settings) -> None:
    task_ids = run_task_async(reconcile_knowledge_graphs(settings))
    for task_id in task_ids:
        run_knowledge_task_job.apply_async(args=(task_id,))


def _recover_knowledge_storage_cleanups(_settings: Settings) -> None:
    cleanup_ids = run_task_async(list_due_knowledge_storage_cleanup_ids())
    for cleanup_id in cleanup_ids:
        run_storage_cleanup_job.apply_async(args=("knowledge", cleanup_id))


def _recover_upload_storage_cleanups(_settings: Settings) -> None:
    cleanup_ids = run_task_async(prepare_due_upload_cleanups())
    for cleanup_id in cleanup_ids:
        run_storage_cleanup_job.apply_async(args=("upload", cleanup_id))


FREQUENT_MAINTENANCE_STEPS: tuple[MaintenanceStep, ...] = (
    ("recover_knowledge_tasks", _recover_knowledge_tasks),
    ("recover_unified_agent_runs", _recover_unified_agent_runs),
    ("recover_legacy_agent_runs", _recover_legacy_agent_runs),
    ("recover_tool_invocations", _recover_tool_invocations),
    ("recover_email_deliveries", _recover_email_deliveries),
)
MINUTELY_MAINTENANCE_STEPS: tuple[MaintenanceStep, ...] = (
    ("cleanup_expired_artifacts", _cleanup_expired_artifacts),
    ("reconcile_knowledge_graphs", _reconcile_knowledge_graphs),
    ("recover_knowledge_storage_cleanups", _recover_knowledge_storage_cleanups),
    ("recover_upload_storage_cleanups", _recover_upload_storage_cleanups),
)


def _run_maintenance_steps(
    steps: tuple[MaintenanceStep, ...],
    settings: Settings,
) -> None:
    for step_name, step in steps:
        try:
            step(settings)
        except Exception as exc:
            log_error(
                logger,
                "Periodic maintenance step failed; the next sweep will retry.",
                exc,
                task_name=step_name,
            )


@celery_app.task(name="app.maintenance.run", ignore_result=True)
def run_maintenance_job(cadence: str) -> None:
    if cadence == "frequent":
        steps = FREQUENT_MAINTENANCE_STEPS
    elif cadence == "minutely":
        steps = MINUTELY_MAINTENANCE_STEPS
    else:
        raise ValueError(f"Unsupported maintenance cadence: {cadence}")
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    _run_maintenance_steps(steps, settings)


__all__ = ["run_maintenance_job"]
