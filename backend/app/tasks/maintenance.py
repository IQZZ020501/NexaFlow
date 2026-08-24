import asyncio

from celery import Task

from app.application.artifacts import cleanup_expired_generated_artifacts
from app.infrastructure.celery import celery_app
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger
from app.tasks.agents import recover_agent_runs_job, recover_legacy_agent_runs_job
from app.tasks.email import recover_email_deliveries_job
from app.tasks.knowledge import (
    reconcile_knowledge_graphs_job,
    recover_knowledge_storage_cleanups_job,
    recover_knowledge_tasks_job,
    recover_upload_storage_cleanups_job,
)
from app.tasks.tools import recover_tool_invocations_job

logger = get_logger(__name__)


@celery_app.task(name="app.artifacts.cleanup_expired", ignore_result=True)
def cleanup_expired_generated_artifacts_job() -> None:
    asyncio.run(cleanup_expired_generated_artifacts())


FREQUENT_RECOVERY_TASKS = (
    recover_knowledge_tasks_job,
    recover_agent_runs_job,
    recover_legacy_agent_runs_job,
    recover_tool_invocations_job,
    recover_email_deliveries_job,
)
MINUTELY_RECOVERY_TASKS = (
    cleanup_expired_generated_artifacts_job,
    reconcile_knowledge_graphs_job,
    recover_knowledge_storage_cleanups_job,
    recover_upload_storage_cleanups_job,
)


def _run_recovery_tasks(tasks: tuple[Task, ...]) -> None:
    for task in tasks:
        try:
            task.run()
        except Exception as exc:
            log_error(
                logger,
                "Periodic recovery task failed; the next sweep will retry.",
                exc,
                task_name=task.name,
            )


@celery_app.task(name="app.maintenance.recover_frequent", ignore_result=True)
def recover_frequent_jobs() -> None:
    _run_recovery_tasks(FREQUENT_RECOVERY_TASKS)


@celery_app.task(name="app.maintenance.recover_minutely", ignore_result=True)
def recover_minutely_jobs() -> None:
    _run_recovery_tasks(MINUTELY_RECOVERY_TASKS)
