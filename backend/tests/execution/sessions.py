"""Database-backed Run fencing checks, isolated from application databases."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import tests.support  # noqa: F401
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.support import settings

from app.domain.agents.models import AgentRunState
from app.entities.defaults import utc_now
from app.entities.execution import ExecutionSession
from app.entities.runs import AgentRun
from app.infra.db.base import Base
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.execution import sessions as repository
from app.infra.execution import sessions
from app.infra.execution.profile import execution_profile
from app.ports.execution import ExecutionBusy, ExecutionNotStarted, ExecutionScope


async def check():
    config = replace(
        settings(), opensandbox_api_key="test", opensandbox_image="test-image"
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as db:
        await db.run_sync(Base.metadata.create_all)
    run = AgentRun(
        workspace_id="workspace",
        agent_id="agent",
        requested_by_user_id="user",
        configuration_source="draft",
        status="running_v2",
        worker_task_id="worker-1",
        execution_deadline_at=utc_now() + timedelta(seconds=900),
        application_snapshot={"execution_profile": execution_profile(config)},
    )
    async with factory() as db:
        await runs.create_agent_run(db, run)
        await db.commit()
    scope = ExecutionScope(run.workspace_id, "command", run.id, "worker-1")
    store = sessions.SessionStore()
    try:
        with patch.object(sessions, "get_session_factory", return_value=factory):
            try:
                await store.acquire_existing(config, scope, 10)
            except ExecutionNotStarted:
                pass
            else:
                raise AssertionError("Read created a missing session")
            assert await store.for_run(scope.workspace_id, scope.run_id) == []
            first, _, reset, _ = await store.acquire(config, scope, 10)
            assert (
                not reset
                and first.expires_at
                == run.execution_deadline_at + timedelta(seconds=60)
            )
            try:
                await store.acquire(config, scope, 10)
            except ExecutionBusy:
                pass
            else:
                raise AssertionError("Concurrent holder acquired a live session")
            await store.publish(
                first,
                sandbox_id="guest",
                state="ready",
                environments={"python": {"environment_hash": "hash"}},
            )
            await store.release(first)
            second, _, _, _ = await store.acquire(config, scope, 10)
            assert (
                second.id == first.id
                and second.sandbox_id == "guest"
                and second.environments
            )
            assert second.holder != first.holder
            assert not await store.closing(first, owned=True)
            assert not await store.current(first, scope)
            async with factory() as db:
                await db.execute(
                    update(AgentRunState)
                    .where(AgentRunState.run_id == run.id)
                    .values(worker_task_id="worker-2")
                )
                await db.commit()
            assert not await store.current(second, scope)
            try:
                await store.acquire(config, scope, 10)
            except ExecutionBusy:
                pass
            else:
                raise AssertionError("Old Run worker reacquired its sandbox")
            await store.release(second)
            current, _, _, _ = await store.acquire(
                config, replace(scope, worker_task_id="worker-2"), 10
            )
            assert current.sandbox_id == "guest"
            async with factory() as db:
                from app.domain.execution.models import ExecutionSession as Row

                await db.execute(
                    update(Row)
                    .where(Row.id == current.id)
                    .values(holder_expires_at=utc_now() - timedelta(seconds=1))
                )
                await db.commit()
            takeover, _, _, stale = await store.acquire(
                config, replace(scope, worker_task_id="worker-2"), 10
            )
            assert stale and takeover.sandbox_id == "guest"
            assert not await store.current(
                current, replace(scope, worker_task_id="worker-2")
            )
            current = takeover
            async with factory() as db:
                await db.execute(
                    update(Row)
                    .where(Row.id == current.id)
                    .values(holder_expires_at=utc_now() - timedelta(seconds=1))
                )
                await db.commit()
            takeover, _, _, stale = await store.acquire_existing(
                config, replace(scope, worker_task_id="worker-2"), 10
            )
            assert stale and takeover.sandbox_id == "guest"
            assert not await store.current(
                current, replace(scope, worker_task_id="worker-2")
            )
            current = takeover
            await store.closing(current)
            try:
                await store.acquire(
                    config, replace(scope, worker_task_id="worker-2"), 10
                )
            except ExecutionBusy:
                pass
            else:
                raise AssertionError("Created while previous guest cleanup was pending")
            assert current.id in {row.id for row in await store.reclaimable()}
            await store.closed(current)
            replacement, _, reset, _ = await store.acquire(
                config, replace(scope, worker_task_id="worker-2"), 10
            )
            assert reset and replacement.id != current.id
            async with factory() as db:
                try:
                    await repository.create(
                        db,
                        ExecutionSession(
                            workspace_id=run.workspace_id,
                            run_id=run.id,
                            image="test",
                            profile_fingerprint="test",
                        ),
                    )
                except IntegrityError:
                    await db.rollback()
                else:
                    raise AssertionError("Database admitted duplicate live session")
                await db.execute(
                    update(AgentRunState)
                    .where(AgentRunState.run_id == run.id)
                    .values(status="cancelled")
                )
                await db.commit()
            assert replacement.id in {row.id for row in await store.reclaimable()}
            try:
                await store.acquire(
                    config, replace(scope, worker_task_id="worker-2"), 10
                )
            except ExecutionNotStarted:
                pass
            else:
                raise AssertionError("Cancelled Run executed a command")
            async with factory() as db:
                await db.execute(
                    update(AgentRunState)
                    .where(AgentRunState.run_id == run.id)
                    .values(
                        status="running_v2",
                        execution_deadline_at=utc_now() - timedelta(seconds=1),
                    )
                )
                await db.commit()
            assert replacement.id in {row.id for row in await store.reclaimable()}, (
                "Expired Run was retained until native TTL"
            )
    finally:
        await engine.dispose()


def main():
    asyncio.run(check())
    print("EXECUTION_SESSIONS_OK")


if __name__ == "__main__":
    main()
