from app.application.agent_executor import (
    RUN_FINISHED,
    run_durable_legacy_agent_run,
    run_durable_unified_agent_run,
)
from app.application.workflow_executor import run_durable_workflow_run
from app.infrastructure.config import Settings
from app.infrastructure.repositories import workflow as workflow_repository
from app.infrastructure.session import get_session_factory


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
        if generation != "legacy":
            return RUN_FINISHED
        return await run_durable_workflow_run(run_id, settings, worker_task_id)
    runner = (
        run_durable_unified_agent_run
        if generation == "unified"
        else run_durable_legacy_agent_run
    )
    return await runner(run_id, settings, worker_task_id)
