from app.application.tools.remote_task_cleanup import recover_remote_task_cancellations
from app.domain.tools.mcp.oauth import recover_revocations
from app.infra.config.settings import Settings
from app.infra.queue.celery import celery_app
from app.tasks.runtime import configure_task_worker, run_task_async


@celery_app.task(name="app.mcp.revoke", ignore_result=True)
def recover_mcp_revocations_job():
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    run_task_async(recover_revocations(settings))


@celery_app.task(name="app.mcp.cancel_tasks", ignore_result=True)
def recover_mcp_tasks_job():
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    run_task_async(recover_remote_task_cancellations(settings))
