"""Release wakes the original identities; admission still decides who can run."""

from app.entities.defaults import utc_now
from app.infra.db.repositories.execution.waiters import grant_waiters
from app.infra.db.session import get_session_factory


async def wake_resource_waiters():
    async with get_session_factory()() as db:
        grants = await grant_waiters(db, utc_now())
        await db.commit()
        return grants
