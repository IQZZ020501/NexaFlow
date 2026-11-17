"""Early capacity retry; missed deliveries remain covered by normal recovery."""

from app.application.tools.resource_wait import wake_resource_waiters
from app.infra.config.settings import Settings
from app.infra.queue.celery import celery_app
from app.tasks.agents.jobs import run_agent_job
from app.tasks.runtime import configure_task_worker, run_task_async
from app.tasks.tools.jobs import run_tool_invocation_job


@celery_app.task(name="app.execution.wake", ignore_result=True)
def wake_resource_waiters_job():
    configure_task_worker(Settings.from_env(require_bootstrap=False))
    runs, tests = run_task_async(wake_resource_waiters())
    for run_id, generation in runs:
        run_agent_job.apply_async(
            args=(run_id, generation),
            queue="agents-v2" if generation == "unified" else "agents-legacy",
        )
    for invocation_id in tests:
        run_tool_invocation_job.apply_async(args=(invocation_id,))
