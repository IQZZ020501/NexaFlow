"""Real Redis + isolated SQL placement, quotas and recovery boundaries."""

import asyncio
import json
import os
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import tests.support  # noqa: F401
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.support import settings

from app.adapters.execution.capacity import CapacityScope, SandboxCapacity
from app.adapters.execution.placement import PlacedExecution
from app.domain.agents.models import AgentRunState
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.config.execution_hosts import SandboxHost, host_settings, parse_hosts
from app.infra.db.base import Base
from app.infra.db.repositories.agents import repository as runs
from app.infra.execution import placement, sessions
from app.infra.execution.profile import execution_profile
from app.ports.execution import (
    ExecutionBusy,
    ExecutionOutcomeUnknown,
    ExecutionScope,
    execution_scope,
)


async def check(redis_url):
    label = uuid4().hex[:12]
    hosts = tuple(
        SandboxHost(name, f"http://{name}-{label}.example", "test-key", 2)
        for name in ("first", "second")
    )
    config = replace(settings(), opensandbox_hosts=hosts, celery_broker_url=redis_url)
    config.validate()
    assert execution_profile(config) == execution_profile(
        replace(
            config,
            opensandbox_hosts=tuple(replace(host, api_key="rotated") for host in hosts),
        )
    )
    assert "test-key" not in repr(hosts)
    assert parse_hosts("") == ()
    with patch.dict(os.environ, {"PLACEMENT_TEST_KEY": "test-key"}):
        for key, value in (
            ("memory_budget_mib", "1024"),
            ("cpu_budget", True),
            ("max_sandboxes", 0),
        ):
            try:
                parse_hosts(
                    json.dumps(
                        [
                            {
                                "id": "first",
                                "url": "http://first.example",
                                "api_key_env": "PLACEMENT_TEST_KEY",
                                key: value,
                            }
                        ]
                    )
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError(
                    "Invalid host resource configuration was accepted."
                )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    plans = []
    platform = PlacedExecution(config)
    adapters = [SandboxCapacity(host) for host in host_settings(config)]
    try:
        with (
            patch.object(placement, "get_session_factory", return_value=factory),
            patch.object(sessions, "get_session_factory", return_value=factory),
        ):

            async def create_run(workspace):
                run = AgentRun(
                    workspace_id=workspace,
                    agent_id="agent",
                    execution_user_id="owner",
                    requested_by_user_id="owner",
                    configuration_source="draft",
                    status="running_v2",
                    worker_task_id="worker",
                    execution_deadline_at=utc_now() + timedelta(seconds=300),
                    application_snapshot={
                        "execution_profile": execution_profile(config),
                        "sandbox_requirements": {"profiles": ["standard", "standard"]},
                    },
                )
                async with factory() as db:
                    await runs.create_agent_run(db, run)
                    await db.commit()
                plans.append(run)
                return run, ExecutionScope(workspace, "invoke", run.id, "worker")

            a, scope_a = await create_run("a-" + label)
            b, scope_b = await create_run("b-" + label)
            first = await platform.store.select(config, scope_a, platform._reserve)
            second = await platform.store.select(config, scope_b, platform._reserve)
            assert first.opensandbox_host_id != second.opensandbox_host_id
            # The same Run stays on its first host, including stdio admission.
            assert (
                await platform.store.select(config, scope_a, platform._reserve) == first
            )
            record, _, _, _ = await sessions.SessionStore().acquire(
                first, scope_a, 10, purpose="mcp", owner_key="integration"
            )
            assert record.host_id == first.opensandbox_host_id
            await sessions.SessionStore().release(record)

            # Restore both host and cross-host tenant accounting after loss of
            # Redis arbitration state. No third bundle may overcommit the hosts.
            for capacity in adapters:
                async with capacity._redis() as redis:
                    await redis.delete(
                        *[key async for key in redis.scan_iter(capacity.key + "*")]
                    )
            c, scope_c = await create_run("c-" + label)
            try:
                await platform.store.select(config, scope_c, platform._reserve)
            except ExecutionBusy as exc:
                assert exc.reason in {"host_capacity", "fair_queue"}
            else:
                raise AssertionError("Lost Redis state allowed host overcommit.")

            # A changed endpoint cannot reconnect or migrate an existing Run.
            changed = replace(
                config,
                opensandbox_hosts=tuple(
                    replace(host, url=host.url + "/changed")
                    if host.id == first.opensandbox_host_id
                    else host
                    for host in hosts
                ),
            )
            try:
                await platform.store.existing(changed, a.workspace_id, a.id)
            except Exception as exc:
                assert "binding changed" in str(exc)
            else:
                raise AssertionError("A host ID was reused with a different endpoint.")

            token = execution_scope.set(scope_a)
            try:
                with patch(
                    "app.adapters.execution.placement.OpenSandboxExecution.execute",
                    AsyncMock(side_effect=ExecutionOutcomeUnknown("unknown")),
                ) as execute:
                    try:
                        await platform.execute(
                            {"execution_session": "agent_run"},
                            timeout_seconds=5,
                            max_output_bytes=1000,
                        )
                    except ExecutionOutcomeUnknown:
                        pass
                    else:
                        raise AssertionError("Unknown outcome was hidden.")
                    assert execute.await_count == 1
            finally:
                execution_scope.reset(token)

            # The canceled Run keeps capacity until its guest is confirmed gone.
            async with factory() as db:
                await db.execute(
                    update(AgentRunState)
                    .where(AgentRunState.run_id == a.id)
                    .values(status="cancelled")
                )
                await db.commit()
            assert await platform.store.release_due() == []
            await sessions.SessionStore().closed(record)
            due = await platform.store.release_due()
            assert len(due) == 1 and due[0].run_id == a.id
            await SandboxCapacity(first).release_reservation(
                due[0].id, CapacityScope(workspace_key=a.workspace_id)
            )
            assert (
                await platform.store.select(config, scope_c, platform._reserve)
            ).opensandbox_host_id == first.opensandbox_host_id
    finally:
        for capacity in adapters:
            async with capacity._redis() as redis:
                keys = [key async for key in redis.scan_iter(capacity.key + "*")]
                keys += [
                    key
                    async for key in redis.scan_iter(
                        f"nexaflow:opensandbox:scopes:*:*{label}*"
                    )
                ]
                if keys:
                    await redis.delete(*keys)
        await engine.dispose()
    print("EXECUTION_PLACEMENT_OK")


if __name__ == "__main__":
    asyncio.run(check(os.environ["NEXAFLOW_TEST_REDIS_URL"]))
