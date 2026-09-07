from app.application.agents.runs.executor import (
    RUN_FINISHED,
    run_durable_legacy_agent_run,
    run_durable_unified_agent_run,
)
from app.application.agents.runs.children import reconcile_workflow_agent_children
from app.application.workflows.runs.executor import run_durable_workflow_run
from app.infra.config.settings import Settings
from app.infra.db.repositories.workflows import repository as workflow_repository
from app.infra.db.session import get_session_factory
from app.infra.observability.errors import log_error
from app.infra.observability.logger import get_logger, log_event
from app.infra.queue.celery import publish_task

logger = get_logger(__name__)

async def run_durable_application_run(
    run_id: str,
    settings: Settings,
    worker_task_id: str | None = None,
    *,
    generation: str = "legacy",
) -> str:
    async with get_session_factory()() as db:
        workflow = await workflow_repository.get_run_detail(db, run_id)
    if workflow is not None:
        return await run_durable_workflow_run(
            run_id,
            settings,
            worker_task_id,
            generation=generation,
        )
    runner = (
        run_durable_unified_agent_run
        if generation == "unified"
        else run_durable_legacy_agent_run
    )
    outcome = await runner(run_id, settings, worker_task_id)
    await reconcile_workflow_agent_children(
        settings,
        child_run_id=run_id,
    )
    return outcome



async def enqueue_agent_run(
    run_id: str,
    settings: Settings,
    *,
    generation: str = "legacy",
) -> None:
    """Publish an agent run by stable task name; eager mode runs it inline."""
    import asyncio
    import logging
    import os

    queue = "agents-v2" if generation == "unified" else "agents-legacy"
    if settings.celery_task_always_eager:
        await run_durable_application_run(
            run_id,
            settings,
            generation=generation,
        )
        return

    task_name = "app.agents.run_v2" if generation == "unified" else "app.agents.run"
    try:
        await publish_task(
            task_name,
            (run_id,),
            settings=settings,
            queue=queue,
        )
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
