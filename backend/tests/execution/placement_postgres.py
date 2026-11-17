"""Concurrent placement requires explicit isolated PostgreSQL and Redis URLs."""

import asyncio
import os
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import tests.support  # noqa: F401
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.support import settings

from app.adapters.execution.capacity import SandboxCapacity
from app.adapters.execution.placement import PlacedExecution
from app.domain.agents.models import Agent, AgentRunState
from app.domain.agents.models import AgentRun as RunRow
from app.domain.execution.models import ExecutionPlacement as PlacementRow
from app.domain.models.registered import RegisteredModel
from app.domain.platform.models import User, Workspace
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.config.execution_hosts import SandboxHost, host_settings
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.execution import placements
from app.infra.execution import placement
from app.infra.execution.profile import execution_profile
from app.ports.execution import ExecutionBusy, ExecutionScope


async def check(database, redis_url):
    assert database.startswith("postgresql+psycopg://")
    label = uuid4().hex
    config = replace(
        settings(),
        celery_broker_url=redis_url,
        opensandbox_max_sandboxes_per_workspace=8,
        opensandbox_hosts=tuple(
            SandboxHost(name, f"http://{name}-{label}.example", "test-key", 2)
            for name in ("first", "second")
        ),
    )
    engine = create_async_engine(database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = [str(uuid4()) for _ in range(4)]
    user_id, workspace_id, model_id, agent_id = ids
    created = []
    capacities = [SandboxCapacity(host) for host in host_settings(config)]
    platform = PlacedExecution(config)
    try:
        async with factory() as db:
            db.add(
                User(
                    id=user_id,
                    username="placement-" + label,
                    email=label + "@example.com",
                    name="Placement fixture",
                    password_hash="disabled-test-account",
                    is_active=False,
                )
            )
            db.add(
                Workspace(
                    id=workspace_id,
                    name="Placement " + label,
                    slug="placement-" + label,
                )
            )
            await db.flush()
            db.add(
                RegisteredModel(
                    id=model_id,
                    workspace_id=workspace_id,
                    name="fixture",
                    provider="fixture",
                    provider_type="openai_compatible",
                    api_base="https://unused.example",
                    model_type="LLM",
                    model_name="unused",
                    created_by_user_id=user_id,
                )
            )
            await db.flush()
            db.add(
                Agent(
                    id=agent_id,
                    workspace_id=workspace_id,
                    name="fixture",
                    model_id=model_id,
                    instructions="",
                    created_by_user_id=user_id,
                )
            )
            await db.flush()
            for _ in range(8):
                run = AgentRun(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    requested_by_user_id=user_id,
                    execution_user_id=user_id,
                    configuration_source="draft",
                    status="running_v2",
                    worker_task_id="worker",
                    execution_deadline_at=utc_now() + timedelta(seconds=300),
                    application_snapshot={
                        "execution_profile": execution_profile(config),
                        "sandbox_requirements": {"profiles": ["standard", "standard"]},
                    },
                )
                await runs.create_agent_run(db, run)
                created.append(run)
            await db.commit()

        async def select_host(run):
            return await platform.store.select(
                config,
                ExecutionScope(workspace_id, "invoke", run.id, "worker"),
                platform._reserve,
            )

        with patch.object(placement, "get_session_factory", return_value=factory):
            same_run = await asyncio.gather(
                *(select_host(created[0]) for _ in range(8))
            )
            assert len({item.opensandbox_host_id for item in same_run}) == 1
            outcomes = await asyncio.gather(
                *(select_host(run) for run in created[1:]), return_exceptions=True
            )
            accepted = [
                item for item in outcomes if not isinstance(item, BaseException)
            ]
            assert (
                len(accepted) == 1
                and accepted[0].opensandbox_host_id != same_run[0].opensandbox_host_id
            )
            assert all(
                isinstance(item, ExecutionBusy)
                for item in outcomes
                if isinstance(item, BaseException)
            ), outcomes
            for capacity in capacities:
                async with capacity._redis() as redis:
                    assert await redis.zcard(capacity.key) == 2
                    keys = [key async for key in redis.scan_iter(capacity.key + "*")]
                    if keys:
                        await redis.delete(*keys)
            try:
                await select_host(created[-1])
            except ExecutionBusy:
                pass
            else:
                raise AssertionError(
                    "PostgreSQL recovery lost outstanding host reservations."
                )
            print("POSTGRES_CONCURRENT_PLACEMENT_OK")
    finally:
        async with factory() as db:
            await db.execute(
                update(AgentRunState)
                .where(AgentRunState.run_id.in_([run.id for run in created]))
                .values(status="cancelled")
            )
            for row in await placements.active(db, utc_now()):
                if row.workspace_id == workspace_id:
                    await placements.release(db, row.id)
            await db.commit()
        for capacity in capacities:
            async with capacity._redis() as redis:
                keys = [key async for key in redis.scan_iter(capacity.key + "*")]
                keys.append(capacity._scope_key("workspace", workspace_id))
                await redis.delete(*keys)
        async with factory() as db:
            await db.execute(
                delete(PlacementRow).where(PlacementRow.workspace_id == workspace_id)
            )
            await db.execute(delete(RunRow).where(RunRow.agent_id == agent_id))
            await db.execute(delete(Agent).where(Agent.id == agent_id))
            await db.execute(
                delete(RegisteredModel).where(RegisteredModel.id == model_id)
            )
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(
        check(
            os.environ["NEXAFLOW_TEST_DATABASE_URL"],
            os.environ["NEXAFLOW_TEST_REDIS_URL"],
        )
    )
