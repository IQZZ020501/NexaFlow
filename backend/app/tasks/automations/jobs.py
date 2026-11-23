"""Celery jobs dispatching persisted automation executions."""

from app.application.automations import dispatch_execution_by_id
from app.infra.config.settings import Settings
from app.infra.queue.celery import celery_app
from app.tasks.runtime import configure_task_worker, run_task_async


@celery_app.task(name="app.automations.dispatch", ignore_result=True)
def dispatch_automation_execution_job(execution_id: str) -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    run_task_async(dispatch_execution_by_id(execution_id, settings))


__all__ = [
    "dispatch_automation_execution_job",
]
