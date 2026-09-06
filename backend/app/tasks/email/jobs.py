from app.application.email.delivery import (
    list_due_email_delivery_ids,
    run_email_delivery,
)
from app.infra.queue.celery import celery_app
from app.infra.config.settings import Settings
from app.infra.observability.errors import log_error
from app.infra.observability.logger import get_logger
from app.tasks.runtime import configure_task_worker, run_task_async

logger = get_logger(__name__)


@celery_app.task(name="app.email.send", ignore_result=True)
def run_email_delivery_job(delivery_id: str) -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    try:
        run_task_async(run_email_delivery(delivery_id, settings))
    except Exception as exc:
        # The persisted lease and Beat recovery are the retry source of truth.
        log_error(
            logger,
            "Email delivery job crashed; recovery remains queued.",
            exc,
            delivery_id=delivery_id,
        )


@celery_app.task(name="app.email.recover", ignore_result=True)
def recover_email_deliveries_job() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    for delivery_id in run_task_async(list_due_email_delivery_ids()):
        run_email_delivery_job.apply_async(args=(delivery_id,))
