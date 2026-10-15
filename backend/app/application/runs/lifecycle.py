"""Agent run orchestration.

Sibling module of ``app.application.agents`` (which re-exports the public
surface): preparing, executing, streaming, and listing agent runs.
"""


from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.defaults import utc_now
from app.infra.db.repositories.agents import repository as agent_repository
from app.infra.db.repositories.execution import sessions as execution_repository
from app.infra.db.repositories.tools import repository as tool_repository

AGENT_EVENT_PAGE_SIZE = 200




async def cancel_run_tree(db: AsyncSession, run_id: str) -> bool:
    now = utc_now()
    run_ids = await agent_repository.cancel_agent_run_tree(db, run_id, now)
    if not run_ids:
        return False
    await tool_repository.settle_cancelled_agent_tool_invocations(db, run_ids, now)
    await execution_repository.close_runs(db, run_ids)
    db.info.setdefault("cancelled_execution_runs", set()).update(run_ids)
    return True


async def close_cancelled_execution_sessions(db: AsyncSession) -> None:
    """Close after cancellation commits; durable closing rows cover outages."""
    from app.infra.config.settings import Settings
    from app.ports.execution import build_execution_platform
    from app.ports.mcp import close_mcp_run_sessions

    run_ids = db.info.pop("cancelled_execution_runs", set())
    if not run_ids:
        return
    platform = build_execution_platform(Settings.from_env(require_bootstrap=False))
    for run_id in run_ids:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        if run:
            try:
                await close_mcp_run_sessions(run_id)
                await platform.close_session(run.workspace_id, run_id)
            except Exception:
                # Beat retries the cleanup intent committed with cancellation.
                import logging
                logging.getLogger(__name__).warning("Run sandbox cleanup will be retried", exc_info=True)
