"""Shared ownership heartbeat for durable Agent and Workflow runs."""

import asyncio
from datetime import timedelta

from app.entities.defaults import utc_now
from app.infra.config.settings import Settings
from app.infra.db.repositories.agents import repository as agent_repository
from app.infra.db.session import get_session_factory


async def maintain_agent_run_lease(
    run_id: str,
    worker_task_id: str,
    settings: Settings,
    lease_lost: asyncio.Event,
) -> None:
    while True:
        await asyncio.sleep(settings.agent_executor_heartbeat_seconds)
        try:
            async with get_session_factory()() as db:
                renewed = await agent_repository.renew_agent_run_lease(
                    db,
                    run_id,
                    worker_task_id,
                    utc_now()
                    + timedelta(seconds=settings.agent_executor_lease_seconds),
                )
                await db.commit()
            if not renewed:
                lease_lost.set()
                return
        except Exception:
            lease_lost.set()
            return


__all__ = [
    "maintain_agent_run_lease",
]
