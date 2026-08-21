import asyncio
import logging
import os

from app.application.knowledge_evaluation import run_evaluation_task
from app.application.knowledge_graph_build import run_graph_build_task
from app.application.knowledge_graph_maintenance import reconcile_knowledge_graphs
from app.infrastructure.celery import celery_app
from app.infrastructure.config import Settings
from app.infrastructure.errors import classify_error, log_error
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.session import get_session_factory
from app.shareddomain.knowledge.task_runner import (
    TASK_LEASE_RENEW_SECONDS,
    TASK_RUN_BUSY,
    list_recoverable_knowledge_task_ids,
    mark_knowledge_task_failed,
    run_knowledge_task,
)
from app.shareddomain.knowledge.cleanup import (
    list_due_knowledge_storage_cleanup_ids,
    run_knowledge_storage_cleanup,
)
from app.shareddomain.workflows.uploads import (
    prepare_due_upload_cleanups,
    run_upload_storage_cleanup,
)
from app.tasks import configure_task_worker

logger = get_logger(__name__)

@celery_app.task(
    bind=True,
    name="app.knowledge.run_task",
    ignore_result=True,
    max_retries=None,
    soft_time_limit=900,
    time_limit=960,
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
        outcome = asyncio.run(
            run_knowledge_task(
                task_id,
                settings,
                enqueue_knowledge_task,
                evaluation_runner=run_evaluation_task,
                graph_runner=run_graph_build_task,
            )
        )
    except Exception as exc:
        log_error(
            logger,
            "Knowledge task job crashed.",
            None,
            source=classify_error(exc),
            task_id=task_id,
            error_type=type(exc).__name__,
        )
        raise
    if outcome == TASK_RUN_BUSY:
        log_event(
            logger,
            logging.WARNING,
            "Knowledge task lease busy; retrying.",
            task_id=task_id,
        )
        raise self.retry(countdown=TASK_LEASE_RENEW_SECONDS)


@celery_app.task(
    name="app.knowledge.recover",
    ignore_result=True,
)
def recover_knowledge_tasks_job() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    task_ids = asyncio.run(list_recoverable_knowledge_task_ids(settings))
    for task_id in task_ids:
        run_knowledge_task_job.apply_async(args=(task_id,))


@celery_app.task(
    name="app.knowledge.reconcile_graphs",
    ignore_result=True,
)
def reconcile_knowledge_graphs_job() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    task_ids = asyncio.run(reconcile_knowledge_graphs(settings))
    for task_id in task_ids:
        run_knowledge_task_job.apply_async(args=(task_id,))


@celery_app.task(
    bind=True,
    name="app.knowledge.cleanup_storage",
    ignore_result=True,
    max_retries=None,
)
def run_knowledge_storage_cleanup_job(self, cleanup_id: str) -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    try:
        asyncio.run(run_knowledge_storage_cleanup(cleanup_id, settings))
    except Exception as exc:
        log_error(
            logger,
            "Knowledge storage cleanup failed; retrying.",
            exc,
            cleanup_id=cleanup_id,
        )
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(
    name="app.knowledge.recover_storage_cleanups",
    ignore_result=True,
)
def recover_knowledge_storage_cleanups_job() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    cleanup_ids = asyncio.run(list_due_knowledge_storage_cleanup_ids())
    for cleanup_id in cleanup_ids:
        run_knowledge_storage_cleanup_job.apply_async(args=(cleanup_id,))


@celery_app.task(
    bind=True,
    name="app.uploads.cleanup_storage",
    ignore_result=True,
    max_retries=None,
)
def run_upload_storage_cleanup_job(self, cleanup_id: str) -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    try:
        asyncio.run(run_upload_storage_cleanup(cleanup_id, settings))
    except Exception as exc:
        log_error(
            logger,
            "Upload storage cleanup failed; retrying.",
            exc,
            cleanup_id=cleanup_id,
        )
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(
    name="app.uploads.recover_storage_cleanups",
    ignore_result=True,
)
def recover_upload_storage_cleanups_job() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    cleanup_ids = asyncio.run(prepare_due_upload_cleanups())
    for cleanup_id in cleanup_ids:
        run_upload_storage_cleanup_job.apply_async(args=(cleanup_id,))


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
        await run_knowledge_task(
            task_id,
            settings,
            enqueue_knowledge_task,
            evaluation_runner=run_evaluation_task,
            graph_runner=run_graph_build_task,
        )
        return

    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        task_always_eager=False,
    )
    try:
        await asyncio.to_thread(run_knowledge_task_job.apply_async, args=(task_id,))
    except Exception as exc:
        log_error(
            logger,
            "Failed to dispatch knowledge task.",
            None,
            source=classify_error(exc),
            task_id=task_id,
            error_type=type(exc).__name__,
        )
        try:
            await mark_task_dispatch_failed(task_id)
        except Exception:
            pass
        raise


async def enqueue_knowledge_storage_cleanup(
    cleanup_id: str,
    settings: Settings,
) -> None:
    if settings.celery_task_always_eager:
        try:
            await run_knowledge_storage_cleanup(cleanup_id, settings)
        except Exception as exc:
            log_error(
                logger,
                "Knowledge storage cleanup deferred after eager failure.",
                exc,
                cleanup_id=cleanup_id,
            )
        return

    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        task_always_eager=False,
    )
    try:
        await asyncio.to_thread(
            run_knowledge_storage_cleanup_job.apply_async,
            args=(cleanup_id,),
        )
    except Exception as exc:
        log_error(
            logger,
            "Knowledge storage cleanup dispatch deferred.",
            exc,
            cleanup_id=cleanup_id,
        )


async def enqueue_upload_storage_cleanups(
    cleanup_ids: list[str],
    settings: Settings,
) -> None:
    eager = settings.celery_task_always_eager
    if not eager:
        celery_app.conf.update(
            broker_url=settings.celery_broker_url,
            task_always_eager=False,
        )
    for cleanup_id in cleanup_ids:
        if eager:
            try:
                await run_upload_storage_cleanup(cleanup_id, settings)
            except Exception as exc:
                log_error(
                    logger,
                    "Upload storage cleanup deferred after eager failure.",
                    exc,
                    cleanup_id=cleanup_id,
                )
            continue
        try:
            await asyncio.to_thread(
                run_upload_storage_cleanup_job.apply_async,
                args=(cleanup_id,),
            )
        except Exception as exc:
            log_error(
                logger,
                "Upload storage cleanup dispatch deferred.",
                exc,
                cleanup_id=cleanup_id,
            )
