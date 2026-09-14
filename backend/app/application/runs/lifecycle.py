"""Agent run orchestration.

Sibling module of ``app.application.agents`` (which re-exports the public
surface): preparing, executing, streaming, and listing agent runs.
"""


from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.defaults import utc_now
from app.infra.db.repositories.agents import repository as agent_repository
from app.infra.db.repositories.tools import repository as tool_repository

AGENT_EVENT_PAGE_SIZE = 200




async def cancel_run_tree(db: AsyncSession, run_id: str) -> bool:
    now = utc_now()
    run_ids = await agent_repository.cancel_agent_run_tree(db, run_id, now)
    if not run_ids:
        return False
    await tool_repository.settle_cancelled_agent_tool_invocations(db, run_ids, now)
    return True
