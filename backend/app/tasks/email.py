import asyncio

from app.application.email import (
    list_due_email_delivery_ids,
    run_email_delivery,
)
from app.infrastructure.celery import celery_app
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger
from app.tasks import configure_task_worker

logger = get_logger(__name__)


@celery_app.task(name="app.email.send", ignore_result=True)
def run_email_delivery_job(delivery_id: str) -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    try:
        asyncio.run(run_email_delivery(delivery_id, settings))
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
    for delivery_id in asyncio.run(list_due_email_delivery_ids()):
        run_email_delivery_job.apply_async(args=(delivery_id,))
