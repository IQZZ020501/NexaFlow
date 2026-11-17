"""A release wakes original durable identities without changing their budgets."""

import asyncio
from datetime import timedelta

import tests.support  # noqa: F401
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.agents.models import AgentRunState
from app.domain.tools.models import ToolInvocation
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.db.base import Base
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.execution.waiters import grant_waiters


async def check():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = utc_now()
    wait = {
        "schema_version": 1,
        "first_wait_at": now.isoformat(),
        "deadline_at": (now + timedelta(seconds=300)).isoformat(),
        "next_attempt_at": (now + timedelta(seconds=30)).isoformat(),
        "reason": "host_capacity",
    }
    run = AgentRun(
        workspace_id="workspace",
        agent_id="agent",
        requested_by_user_id="owner",
        execution_user_id="owner",
        status="queued_v2",
        configuration_source="draft",
    )
    try:
        async with factory() as db:
            await runs.create_agent_run(db, run)
            for identity, parent in (("agent", run.id), ("test", None)):
                db.add(
                    ToolInvocation(
                        id=identity,
                        workspace_id="workspace",
                        origin=identity,
                        run_id=parent,
                    root_run_id=parent,
                        invocation_id=identity,
                        execution_user_id="owner",
                        access_source="console",
                        policy_snapshot={},
                        arguments={},
                        arguments_hash="a" * 64,
                        idempotency_key=identity,
                        status="queued",
                        error_code="tool_resource_wait",
                        resource_wait=wait,
                        attempts=0,
                    )
                )
            await db.commit()
        async with factory() as db:
            original_updated = await db.scalar(
                select(AgentRunState.updated_at).where(AgentRunState.run_id == run.id)
            )
            granted_runs, granted_tests = await grant_waiters(db, now)
            assert granted_runs == [(run.id, "unified")] and granted_tests == ["test"]
            await db.commit()
        async with factory() as db:
            assert await grant_waiters(db, now + timedelta(seconds=1)) == ([], [])
            invocation = await db.get(ToolInvocation, "agent")
            assert invocation.attempts == 0 and invocation.idempotency_key == "agent"
            assert invocation.resource_wait["deadline_at"] == wait["deadline_at"]
            assert invocation.resource_wait["first_wait_at"] == wait["first_wait_at"]
            assert invocation.resource_wait["next_attempt_at"] == now.isoformat()
            assert (
                await db.scalar(
                    select(AgentRunState.updated_at).where(
                        AgentRunState.run_id == run.id
                    )
                )
                == original_updated
            )
            await db.execute(
                update(AgentRunState)
                .where(AgentRunState.run_id == run.id)
                .values(
                    status="running_v2",
                    worker_task_id="live",
                    lease_expires_at=now + timedelta(seconds=120),
                )
            )
            await db.commit()
        async with factory() as db:
            granted_runs, _ = await grant_waiters(db, now + timedelta(seconds=10))
            assert not granted_runs, "A wake bypassed a live Run lease."
        print("EXECUTION_WAKEUP_OK")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check())
