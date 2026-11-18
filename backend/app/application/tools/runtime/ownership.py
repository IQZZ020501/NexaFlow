"""Invocation heartbeat and short ownership fences at side-effect boundaries."""

import asyncio
from datetime import timedelta

from app.entities.defaults import utc_now
from app.infra.db.repositories.tools import repository
from app.infra.db.session import get_session_factory
from app.ports.tools import ToolInvocationOwnershipLost


async def require_ownership(db, context, *, renew_until=None, require_live_lease=True):
    if context.ownership_lost is not None and context.ownership_lost.is_set():
        raise ToolInvocationOwnershipLost("Tool invocation ownership was lost.")
    invocation = await repository.owned_tool_invocation(
        db,
        context,
        utc_now(),
        renew_until=renew_until,
        require_live_lease=require_live_lease,
    )
    if invocation is None:
        if context.ownership_lost is not None:
            context.ownership_lost.set()
        raise ToolInvocationOwnershipLost("Tool invocation ownership was lost.")
    return invocation


async def invoke_owned(
    adapter, snapshot, arguments, context, settings, run_lease_lost=None
):
    stop = asyncio.Event()

    async def heartbeat():
        interval = min(
            settings.agent_executor_heartbeat_seconds,
            settings.agent_executor_lease_seconds / 3,
        )
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), interval)
                return
            except TimeoutError:
                pass
            async with get_session_factory()() as db:
                await require_ownership(
                    db,
                    context,
                    renew_until=utc_now()
                    + timedelta(seconds=settings.agent_executor_lease_seconds),
                )
                await db.commit()

    async def run_signal():
        await run_lease_lost.wait()
        raise ToolInvocationOwnershipLost("Run ownership was lost.")

    # Check before starting an adapter, including when its first await prepares
    # credentials or creates an execution host.
    if run_lease_lost is not None and run_lease_lost.is_set():
        context.ownership_lost.set()
        raise ToolInvocationOwnershipLost("Run ownership was lost.")
    async with get_session_factory()() as db:
        await require_ownership(db, context)
        await db.commit()
    work = asyncio.create_task(adapter.invoke(snapshot, arguments, context))
    monitor = asyncio.create_task(heartbeat())
    signal = asyncio.create_task(run_signal()) if run_lease_lost is not None else None
    try:
        tasks = {work, monitor, *([signal] if signal else [])}
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if signal is not None and signal in done:
            context.ownership_lost.set()
            await signal
        if monitor in done:
            context.ownership_lost.set()
            await monitor
        return await work
    finally:
        stop.set()
        work.cancel()
        if signal:
            signal.cancel()
        # Let an in-flight renewal commit/rollback; cancelling a database call
        # needlessly invalidates the connection after every successful tool.
        await asyncio.gather(*tasks, return_exceptions=True)
