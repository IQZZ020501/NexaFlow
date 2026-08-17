import asyncio
import logging
import os

from app.application.agent_executor import (
    RUN_BUSY,
    list_recoverable_legacy_agent_run_ids,
    list_recoverable_unified_agent_run_ids,
)
from app.application.run_dispatch import run_durable_application_run
from app.infrastructure.celery import celery_app
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger, log_event
from app.tasks import configure_task_worker

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.agents.run",
    ignore_result=True,
    max_retries=None,
)
def run_agent_job(self, run_id: str) -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    try:
        outcome = asyncio.run(
            run_durable_application_run(run_id, settings, worker_task_id=self.request.id)
        )
    except Exception as exc:
        log_error(logger, "Agent worker job crashed.", exc, agent_run_id=run_id)
        raise
    if outcome == RUN_BUSY:
        raise self.retry(
            countdown=settings.agent_executor_heartbeat_seconds,
            queue="agents-legacy",
        )


@celery_app.task(
    bind=True,
    name="app.agents.run_v2",
    ignore_result=True,
    max_retries=None,
)
def run_unified_agent_job(self, run_id: str) -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    try:
        outcome = asyncio.run(
            run_durable_application_run(
                run_id,
                settings,
                worker_task_id=self.request.id,
                generation="unified",
            )
        )
    except Exception as exc:
        log_error(logger, "Unified Agent worker job crashed.", exc, agent_run_id=run_id)
        raise
    if outcome == RUN_BUSY:
        raise self.retry(
            countdown=settings.agent_executor_heartbeat_seconds,
            queue="agents-v2",
        )


@celery_app.task(
    name="app.agents.recover",
    ignore_result=True,
)
def recover_agent_runs_job() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    run_ids = asyncio.run(list_recoverable_unified_agent_run_ids(settings))
    for run_id in run_ids:
        run_unified_agent_job.apply_async(args=(run_id,), queue="agents-v2")


@celery_app.task(
    name="app.agents.recover_legacy",
    ignore_result=True,
)
def recover_legacy_agent_runs_job() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    run_ids = asyncio.run(list_recoverable_legacy_agent_run_ids(settings))
    for run_id in run_ids:
        run_agent_job.apply_async(args=(run_id,), queue="agents-legacy")


async def enqueue_agent_run(
    run_id: str,
    settings: Settings,
    *,
    generation: str = "legacy",
) -> None:
    task = run_unified_agent_job if generation == "unified" else run_agent_job
    queue = "agents-v2" if generation == "unified" else "agents-legacy"
    if settings.celery_task_always_eager:
        await run_durable_application_run(
            run_id,
            settings,
            generation=generation,
        )
        return

    celery_app.conf.update(
        broker_url=settings.celery_broker_url,
        task_always_eager=False,
    )
    try:
        await asyncio.to_thread(task.apply_async, args=(run_id,), queue=queue)
    except Exception as exc:
        log_error(
            logger,
            "Agent queue dispatch deferred to recovery beat.",
            exc,
            agent_run_id=run_id,
            worker_pid=os.getpid(),
        )
    else:
        log_event(
            logger,
            logging.INFO,
            "Agent run queued.",
            agent_run_id=run_id,
        )
