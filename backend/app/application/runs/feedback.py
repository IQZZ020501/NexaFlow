"""Agent run orchestration.

Sibling module of ``app.application.agents`` (which re-exports the public
surface): preparing, executing, streaming, and listing agent runs.
"""


from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agents.models import (
    AGENT_RUN_SUCCEEDED_STATUS,
)
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.db.repositories.agents import repository as agent_repository

AGENT_EVENT_PAGE_SIZE = 200




async def update_run_feedback(
    db: AsyncSession,
    run: AgentRun,
    value: str | None,
) -> AgentRun:
    """
    Update the feedback value for a completed agent run.
    
    Parameters:
    	run (AgentRun): The completed run to update.
    	value (str | None): The feedback value, either `"positive"`, `"negative"`, or `None` to clear existing feedback.
    
    Returns:
    	AgentRun: The refreshed agent run with the updated feedback.
    
    Raises:
    	HTTPException: If the run has no completed result or the feedback value is invalid.
    """
    if run.status != AGENT_RUN_SUCCEEDED_STATUS or not run.result:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Feedback is available only for completed results.",
        )
    if value not in {None, "positive", "negative"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid feedback.")
    if run.feedback == value:
        return run
    run.feedback = value
    run.feedback_updated_at = utc_now() if value is not None else None
    run = await agent_repository.save_agent_run(db, run)
    await db.commit()
    current = await agent_repository.get_agent_run_by_id(db, run.id)
    assert current is not None
    return current
