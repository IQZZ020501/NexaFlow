"""Opt-in two-control-plane smoke; callers supply isolated hosts and Redis."""

from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

import tests.support  # noqa: F401
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.agents.models import AgentRunState
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.db.base import Base
from app.infra.db.repositories.agents import repository as runs
from app.infra.execution import placement, sessions
from app.infra.execution.profile import execution_profile
from app.infra.tools.mcp_stdio import parse_mcp_stdio_config
from app.ports.execution import (
    ExecutionScope,
    build_execution_platform,
    execution_scope,
)
from app.ports.mcp import McpConnection, call_mcp_tool, close_mcp_run_sessions


async def check(config, outage=None):
    assert len(config.opensandbox_hosts) == 2 and config.opensandbox_warm_pool_size == 0
    platform = build_execution_platform(config)
    created = []
    with TemporaryDirectory(prefix="nexaflow-placement-smoke-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{directory}/placement.db")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        with (
            patch.object(placement, "get_session_factory", return_value=factory),
            patch.object(sessions, "get_session_factory", return_value=factory),
        ):
            try:
                for label in ("placement-a", "placement-b"):
                    run = AgentRun(
                        workspace_id=label,
                        agent_id="agent",
                        requested_by_user_id="owner",
                        execution_user_id="owner",
                        status="running_v2",
                        configuration_source="draft",
                        worker_task_id="worker",
                        execution_deadline_at=utc_now() + timedelta(seconds=600),
                        application_snapshot={
                            "execution_profile": execution_profile(config),
                            "sandbox_requirements": {
                                "profiles": ["standard", "standard"]
                            },
                        },
                    )
                    async with factory() as db:
                        await runs.create_agent_run(db, run)
                        await db.commit()
                    created.append(run)

                async def command(run, source, timeout=15):
                    token = execution_scope.set(
                        ExecutionScope(run.workspace_id, "command", run.id, "worker")
                    )
                    try:
                        return await platform.execute(
                            {"command": {"command": source, "timeout_seconds": 5}},
                            timeout_seconds=timeout,
                            max_output_bytes=128 * 1024,
                        )
                    finally:
                        execution_scope.reset(token)

                for run, label in zip(created, ("alpha", "beta")):
                    response = await command(
                        run, f"test ! -e state && printf '{label}' > state && id -u"
                    )
                    assert (
                        response["ok"]
                        and response["exit_code"] == 0
                        and "65532" in response["stdout"]
                    ), response
                store = sessions.SessionStore()
                records = [
                    (await store.for_run(run.workspace_id, run.id))[0]
                    for run in created
                ]
                assert records[0].host_id != records[1].host_id

                source = "from mcp.server.mcpserver import MCPServer\nserver = MCPServer('placement', log_level='ERROR')\n@server.tool()\ndef echo(value: str) -> str:\n return value\nserver.run('stdio')\n"
                run = created[0]
                token = execution_scope.set(
                    ExecutionScope(run.workspace_id, "stdio", run.id, "worker")
                )
                try:
                    result = await call_mcp_tool(
                        McpConnection(
                            transport="stdio",
                            workspace_id=run.workspace_id,
                            stdio_config=parse_mcp_stdio_config(
                                {
                                    "command": "python",
                                    "args": ["-c", source],
                                    "egress_domains": [],
                                }
                            ),
                        ),
                        config,
                        "echo",
                        {"value": "placed"},
                        "stdio-identity",
                    )
                    assert not result.is_error and "placed" in str(result.content), (
                        result
                    )
                    group = await store.for_run(run.workspace_id, run.id)
                    assert {record.purpose for record in group} == {"run", "mcp"}
                    assert {record.host_id for record in group} == {records[0].host_id}
                finally:
                    await close_mcp_run_sessions(run.id)
                    execution_scope.reset(token)

                if outage is not None:
                    target = created[1]
                    await outage(records[1].host_id, True)
                    try:
                        try:
                            await command(
                                target,
                                "printf must-not-migrate > unexpected",
                                timeout=1,
                            )
                        except Exception:
                            pass
                        else:
                            raise AssertionError(
                                "An unavailable control plane accepted work."
                            )
                        current = (await store.for_run(target.workspace_id, target.id))[
                            0
                        ]
                        assert (current.host_id, current.sandbox_id) == (
                            records[1].host_id,
                            records[1].sandbox_id,
                        )
                    finally:
                        await outage(records[1].host_id, False)
                for run, label in zip(created, ("alpha", "beta")):
                    response = await command(run, "cat state; test ! -e unexpected")
                    assert response["exit_code"] == 0 and label in response["stdout"]
                print("TWO_CONTROL_PLANES_PLACEMENT_OK")
            finally:
                for run in created:
                    async with factory() as db:
                        await db.execute(
                            update(AgentRunState)
                            .where(AgentRunState.run_id == run.id)
                            .values(status="cancelled")
                        )
                        await db.commit()
                    await close_mcp_run_sessions(run.id)
                    await platform.close_session(run.workspace_id, run.id)
                    assert not await sessions.SessionStore().for_run(
                        run.workspace_id, run.id
                    )
                await engine.dispose()
