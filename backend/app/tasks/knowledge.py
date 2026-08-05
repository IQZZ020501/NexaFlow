import asyncio
import logging
import os

from app.infrastructure.celery import celery_app
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.session import configure_database, get_session_factory
from app.shareddomain.knowledge.task_runner import (
    TASK_LEASE_RENEW_SECONDS,
    TASK_RUN_BUSY,
    mark_knowledge_task_failed,
    run_knowledge_task,
)

logger = get_logger(__name__)

_configured_process_id: int | None = None


def configure_task_worker(settings: Settings) -> None:
    global _configured_process_id

    process_id = os.getpid()
    if _configured_process_id == process_id:
        return
    configure_database(settings)
    _configured_process_id = process_id


@celery_app.task(
    bind=True,
    name="app.knowledge.run_task",
    ignore_result=True,
    max_retries=None,
)
def run_knowledge_task_job(self, task_id: str) -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    log_event(
        logger,
        logging.INFO,
        "Knowledge task job started.",
        task_id=task_id,
        worker_pid=os.getpid(),
    )
    try:
        outcome = asyncio.run(run_knowledge_task(task_id, settings, enqueue_knowledge_task))
    except Exception as exc:
        log_error(logger, "Knowledge task job crashed.", exc, task_id=task_id)
        raise
    if outcome == TASK_RUN_BUSY:
        log_event(
            logger,
            logging.WARNING,
            "Knowledge task lease busy; retrying.",
            task_id=task_id,
        )
        raise self.retry(countdown=TASK_LEASE_RENEW_SECONDS)


async def mark_task_dispatch_failed(task_id: str) -> None:
    async with get_session_factory()() as db:
        await mark_knowledge_task_failed(
            db,
            task_id,
            "Knowledge task queue is unavailable.",
            only_if_queued=True,
        )


async def enqueue_knowledge_task(task_id: str, settings: Settings) -> None:
    if settings.celery_task_always_eager:
        await run_knowledge_task(task_id, settings, enqueue_knowledge_task)
        return

    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        task_always_eager=False,
    )
    try:
        await asyncio.to_thread(run_knowledge_task_job.apply_async, args=(task_id,))
    except Exception as exc:
        log_error(logger, "Failed to dispatch knowledge task.", exc, task_id=task_id)
        try:
            await mark_task_dispatch_failed(task_id)
        except Exception:
            pass
        raise
