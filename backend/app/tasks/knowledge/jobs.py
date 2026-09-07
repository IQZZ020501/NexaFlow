import logging
import os

from app.application.knowledge.evaluation.runner import run_evaluation_task
from app.application.knowledge.documents.service import enqueue_knowledge_task
from app.application.knowledge.graph.build import run_graph_build_task
from app.application.knowledge.graph.maintenance import reconcile_knowledge_graphs
from app.infra.queue.celery import celery_app
from app.infra.config.settings import Settings
from app.infra.observability.errors import classify_error, log_error
from app.infra.observability.logger import get_logger, log_event
from app.domain.knowledge.tasks.runner import (
    TASK_LEASE_RENEW_SECONDS,
    TASK_RUN_BUSY,
    list_recoverable_knowledge_task_ids,
    mark_knowledge_task_failed,
    run_knowledge_task,
)
from app.domain.knowledge.storage.cleanup import (
    list_due_knowledge_storage_cleanup_ids,
    run_knowledge_storage_cleanup,
)
from app.domain.workflows.uploads import (
    prepare_due_upload_cleanups,
    run_upload_storage_cleanup,
)
from app.tasks.runtime import configure_task_worker, run_task_async

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
        outcome = run_task_async(
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
    task_ids = run_task_async(list_recoverable_knowledge_task_ids(settings))
    for task_id in task_ids:
        run_knowledge_task_job.apply_async(args=(task_id,))


@celery_app.task(
    name="app.knowledge.reconcile_graphs",
    ignore_result=True,
)
def reconcile_knowledge_graphs_job() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    task_ids = run_task_async(reconcile_knowledge_graphs(settings))
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
        run_task_async(run_knowledge_storage_cleanup(cleanup_id, settings))
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
    cleanup_ids = run_task_async(list_due_knowledge_storage_cleanup_ids())
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
        run_task_async(run_upload_storage_cleanup(cleanup_id, settings))
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
    cleanup_ids = run_task_async(prepare_due_upload_cleanups())
    for cleanup_id in cleanup_ids:
        run_upload_storage_cleanup_job.apply_async(args=(cleanup_id,))
