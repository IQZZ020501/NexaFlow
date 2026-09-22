import logging
import os

from app.application.knowledge.documents.service import enqueue_knowledge_task
from app.application.knowledge.evaluation.runner import run_evaluation_task
from app.application.knowledge.graph.build import run_graph_build_task
from app.domain.knowledge.tasks.runner import (
    TASK_LEASE_RENEW_SECONDS,
    TASK_RUN_BUSY,
    run_knowledge_task,
)
from app.infra.config.settings import Settings
from app.infra.observability.errors import classify_error, log_error
from app.infra.observability.logger import get_logger, log_event
from app.infra.queue.celery import celery_app
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
