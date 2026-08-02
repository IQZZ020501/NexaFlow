import asyncio
import os

from app.core.celery import celery_app
from app.core.config import Settings
from app.core.session import configure_database, get_session_factory
from app.services.knowledge_task_runner import (
    TASK_LEASE_RENEW_SECONDS,
    TASK_RUN_BUSY,
    mark_knowledge_task_failed,
    run_knowledge_task,
)

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
    outcome = asyncio.run(run_knowledge_task(task_id, settings, enqueue_knowledge_task))
    if outcome == TASK_RUN_BUSY:
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
    except Exception:
        try:
            await mark_task_dispatch_failed(task_id)
        except Exception:
            pass
        raise
