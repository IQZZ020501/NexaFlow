from app.application.agents.runs.executor import RUN_BUSY
from app.application.runs.dispatch import run_durable_application_run
from app.infra.config.settings import Settings
from app.infra.observability.errors import log_error
from app.infra.observability.logger import get_logger
from app.infra.queue.celery import celery_app
from app.tasks.runtime import configure_task_worker, run_task_async

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.agents.run",
    ignore_result=True,
    max_retries=None,
)
def run_agent_job(self, run_id: str, generation: str = "legacy") -> None:
    if generation not in {"legacy", "unified"}:
        raise ValueError(f"Unsupported Agent worker generation: {generation}")
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    try:
        outcome = run_task_async(
            run_durable_application_run(
                run_id,
                settings,
                worker_task_id=self.request.id,
                generation=generation,
            )
        )
    except Exception as exc:
        log_error(
            logger,
            "Agent worker job crashed.",
            exc,
            agent_run_id=run_id,
            worker_generation=generation,
        )
        raise
    if outcome == RUN_BUSY:
        raise self.retry(
            countdown=settings.agent_executor_heartbeat_seconds,
            queue="agents-v2" if generation == "unified" else "agents-legacy",
        )
