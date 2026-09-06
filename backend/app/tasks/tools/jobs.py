"""Celery entry points for durable Tool test execution."""

from app.application.tools.runtime.service import (
    ToolInvocationBusy,
    execute_tool_invocation,
    list_recoverable_tool_test_invocation_ids,
)
from app.infra.queue.celery import celery_app
from app.infra.config.settings import Settings
from app.tasks.runtime import configure_task_worker, run_task_async


@celery_app.task(
    bind=True,
    name="app.tools.run",
    ignore_result=True,
    max_retries=None,
)
def run_tool_invocation_job(self, invocation_id: str) -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    try:
        run_task_async(
            execute_tool_invocation(
                invocation_id,
                settings,
                worker_task_id=self.request.id,
            )
        )
    except ToolInvocationBusy as exc:
        raise self.retry(
            exc=exc,
            countdown=settings.agent_executor_heartbeat_seconds,
        ) from exc


@celery_app.task(
    name="app.tools.recover",
    ignore_result=True,
)
def recover_tool_invocations_job() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    invocation_ids = run_task_async(list_recoverable_tool_test_invocation_ids())
    for invocation_id in invocation_ids:
        run_tool_invocation_job.apply_async(args=(invocation_id,))


__all__ = [
    "recover_tool_invocations_job",
    "run_tool_invocation_job",
]
