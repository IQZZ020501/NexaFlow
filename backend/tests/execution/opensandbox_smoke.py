"""Opt-in real OpenSandbox checks against a dedicated test execution server.

Run from backend with OPENSANDBOX_API_KEY set; never uses the business database.
The server must already have the execution image and pinned execd/egress images.
"""

import argparse
import asyncio
import base64
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
import tests.support  # noqa: F401
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models import NetworkPolicy, NetworkRule
from opensandbox.models.execd import RunCommandOpts
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.support import settings

from app.adapters.execution import pool
from app.adapters.execution.capacity import SandboxCapacity
from app.adapters.execution.opensandbox import OpenSandboxExecution
from app.domain.execution.models import ExecutionSession as SessionRow
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.db.base import Base
from app.infra.db.repositories.agents import repository as runs
from app.infra.execution import sessions
from app.infra.execution.network import DENIED_NETWORKS
from app.infra.execution.profile import execution_profile
from app.infra.sandbox.client import execute_workflow_code
from app.infra.tools.mcp_stdio import parse_mcp_stdio_config
from app.ports.execution import ExecutionBusy, ExecutionScope, execution_scope
from app.ports.mcp import (
    McpConnection,
    call_mcp_tool,
    close_mcp_run_sessions,
    discover_mcp_tools,
)


def encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


async def assert_live_stdio_mcp(runtime):
    source = (
        "import os\nfrom mcp.server.mcpserver import MCPServer\nfrom pydantic import BaseModel\n"
        "class Echo(BaseModel):\n value: str\n token: str\n business_env_absent: bool\n count: int\n"
        "count = 0\n"
        "server = MCPServer('smoke', log_level='ERROR')\n"
        "@server.tool()\ndef echo(value: str) -> Echo:\n"
        " global count\n count += 1\n"
        " return Echo(value=value, count=count, token=os.environ['MCP_ONLY_TOKEN'], "
        "business_env_absent=not any(k in os.environ for k in "
        "['DATABASE_URL', 'OPENSANDBOX_API_KEY', 'MODEL_SECRET_KEY']))\n"
        "server.run('stdio')\n"
    )
    connection = McpConnection(
        transport="stdio",
        workspace_id="smoke-workspace",
        stdio_config=parse_mcp_stdio_config(
            {
                "command": "python",
                "args": ["-c", source],
                "env": {"MCP_ONLY_TOKEN": "integration-fixture"},
                "egress_domains": [],
            }
        ),
    )
    discovery = await discover_mcp_tools(connection, runtime)
    assert discovery.tools[0]["name"] == "echo", discovery
    result = await call_mcp_tool(
        connection, runtime, "echo", {"value": "isolated"}, "smoke-call"
    )
    assert not result.is_error and result.content
    assert result.structured_content == {
        "value": "isolated",
        "token": "integration-fixture",
        "business_env_absent": True,
        "count": 1,
    }, result
    second = await call_mcp_tool(
        connection, runtime, "echo", {"value": "second"}, "smoke-call-2"
    )
    assert second.structured_content["count"] == 2, second
    await close_mcp_run_sessions("smoke-run")


@asynccontextmanager
async def isolated_run_store(runtime):
    with TemporaryDirectory(prefix="nexaflow-execution-smoke-db-") as temporary:
        engine = create_async_engine(f"sqlite+aiosqlite:///{temporary}/sessions.db")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with factory() as db:
                await runs.create_agent_run(
                    db,
                    AgentRun(
                        id="smoke-run",
                        workspace_id="smoke-workspace",
                        agent_id="smoke-agent",
                        requested_by_user_id="smoke-user",
                        configuration_source="draft",
                        status="running_v2",
                        worker_task_id="smoke-worker",
                        execution_deadline_at=utc_now() + timedelta(seconds=900),
                        application_snapshot={
                            "execution_profile": execution_profile(runtime)
                        },
                    ),
                )
                await db.commit()
            with patch.object(sessions, "get_session_factory", return_value=factory):
                yield
        finally:
            await engine.dispose()


async def assert_live_shell(platform):
    request = {
        "execution_session": "agent_run",
        "command": {
            "command": "echo preserved > state; setsid sleep 60 >/dev/null 2>&1 & echo $! > escaped-pid; sleep .1; printf 'artifact' > outputs/result.txt; id -u; exit 7",
            "timeout_seconds": 5,
        },
        "skill_mounts": {
            "sample-version": {"scripts/main.sh": encoded("echo readonly")}
        },
    }
    response = await platform.execute(
        request, timeout_seconds=15, max_output_bytes=128 * 1024
    )
    assert (
        response["ok"]
        and response["exit_code"] == 7
        and response["stdout"].strip() == "65532"
    ), response
    content = await platform.read_session_file(
        "smoke-workspace",
        "smoke-run",
        response["artifacts"][0]["path"],
        5 * 1024 * 1024,
    )
    assert content == b"artifact"
    # Drop process-local handles to force the next worker to connect by ID.
    for item in list(platform._sessions.values()):
        await item.sandbox.close()
    platform._sessions.clear()
    response = await platform.execute(
        {
            "execution_session": "agent_run",
            "command": {
                "command": "cat state; ! kill -0 $(cat escaped-pid) 2>/dev/null; ! echo tampered >> /skills/sample-version/scripts/main.sh; bash /skills/sample-version/scripts/main.sh; python -c 'import socket; socket.create_connection((\"1.1.1.1\",443),timeout=.2)'",
                "timeout_seconds": 5,
            },
        },
        timeout_seconds=15,
        max_output_bytes=128 * 1024,
    )
    assert (
        response["ok"]
        and response["exit_code"] != 0
        and "preserved" in response["stdout"]
        and "readonly" in response["stdout"]
    ), response
    timed = await platform.execute(
        {
            "execution_session": "agent_run",
            "command": {"command": "sleep 10", "timeout_seconds": 1},
        },
        timeout_seconds=11,
        max_output_bytes=128 * 1024,
    )
    assert timed["ok"] and timed["exit_code"] == 124, timed
    truncated = await platform.execute(
        {
            "execution_session": "agent_run",
            "command": {
                "command": "printf BEGIN; head -c 100000 /dev/zero | tr '\\0' x; printf END",
                "timeout_seconds": 5,
            },
        },
        timeout_seconds=15,
        max_output_bytes=128 * 1024,
    )
    assert (
        truncated["truncated"]
        and truncated["stdout"].startswith("BEGIN")
        and truncated["stdout"].endswith("END")
    ), truncated

    # A dead worker's UID processes must stop before a successor uses the guest.
    record = (await platform.store.for_run("smoke-workspace", "smoke-run"))[0]
    cached = platform._sessions[record.id].sandbox
    await cached.commands.run(
        "setsid sleep 60 >/dev/null 2>&1 & echo $! > /workspace/stale-pid",
        opts=RunCommandOpts(uid=65532, gid=65532),
    )
    async with sessions.get_session_factory()() as db:
        await db.execute(
            update(SessionRow)
            .where(SessionRow.id == record.id)
            .values(
                holder="abandoned", holder_expires_at=utc_now() - timedelta(seconds=1)
            )
        )
        await db.commit()
    takeover = await platform.execute(
        {
            "execution_session": "agent_run",
            "command": {
                "command": "p=$(cat stale-pid); test ! -e /proc/$p/status || grep -q '^State:.*Z' /proc/$p/status",
                "timeout_seconds": 5,
            },
        },
        timeout_seconds=15,
        max_output_bytes=128 * 1024,
    )
    assert takeover["ok"] and takeover["exit_code"] == 0, takeover


async def assert_live_pool_and_capacity(runtime, redis_url):
    """Opt-in shared Redis checks; the URL must be an isolated test instance."""
    platform = OpenSandboxExecution(
        replace(
            runtime,
            celery_broker_url=redis_url,
            opensandbox_warm_pool_size=1,
            opensandbox_max_sandboxes=5,
        )
    )
    guest = None
    slots = []
    capacity = SandboxCapacity(platform.settings)
    assert capacity.limit == 4
    try:
        guest = await platform._create_sandbox(
            None, [], 10, persistent=False, profile="standard"
        )
        await platform._destroy_sandbox(guest)
        guest = None
        sdk_pool = pool._pools[
            (asyncio.get_running_loop(), pool.pool_name(platform.settings, "standard"))
        ]
        async with asyncio.timeout(45):
            while not (idle := await sdk_pool.snapshot_idle_entries()):
                await asyncio.sleep(0.2)
        warmed_id = idle[0].sandbox_id
        guest = await platform._create_sandbox(
            None, [], 10, persistent=False, profile="standard"
        )
        assert guest.id == warmed_id, (
            "An idle sandbox was not acquired from the SDK pool"
        )
        info = await guest.get_info()
        assert (
            info.metadata["owner"] == "nexaflow"
            and info.metadata["purpose"] == "ephemeral"
            and not info.metadata.get("pool")
        ), info
        await platform._require_enforcement(guest, [])
        for _ in range(2):
            slots.append((await capacity.acquire(120, "consumer-a"), "consumer-a"))
        with patch("app.adapters.execution.capacity.ACQUIRE_WAIT_SECONDS", 0):
            try:
                await capacity.acquire(120, "consumer-a")
            except ExecutionBusy:
                pass
            else:
                raise AssertionError("A visitor reserved a third sandbox")
            slots.append((await capacity.acquire(120, "consumer-b"), "consumer-b"))
            try:
                await capacity.acquire(120)
            except ExecutionBusy:
                pass
            else:
                raise AssertionError(
                    "Warm capacity was not deducted from the host limit"
                )
        print("OPENSANDBOX_POOL_CAPACITY_OK")
    finally:
        for token, consumer in slots:
            await capacity.release(token, consumer)
        if guest is not None:
            await platform._destroy_sandbox(guest)
        for key, sdk_pool in list(pool._pools.items()):
            if key[0] is asyncio.get_running_loop():
                await sdk_pool.shutdown()
                await sdk_pool.release_all_idle()
                pool._pools.pop(key, None)


async def assert_live_cleanup(runtime):
    ids = []
    started = asyncio.Event()
    create = Sandbox.create

    async def tracked_create(*args, **kwargs):
        instance = await create(*args, **kwargs)
        ids.append(instance.id)
        command = instance.commands.run

        async def run_command(*args, **kwargs):
            started.set()
            return await command(*args, **kwargs)

        instance.commands.run = run_command
        return instance

    headers = {"OPEN-SANDBOX-API-KEY": runtime.opensandbox_api_key}
    async with httpx.AsyncClient(
        trust_env=False, follow_redirects=False, timeout=10
    ) as client:
        with patch.object(Sandbox, "create", side_effect=tracked_create):
            task = asyncio.create_task(
                OpenSandboxExecution(runtime).execute(
                    {"code": "while True: pass", "limits": {"timeout_ms": 30000}},
                    timeout_seconds=30,
                    max_output_bytes=10000,
                )
            )
            try:
                await asyncio.wait_for(started.wait(), 30)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        assert ids
        info = await client.get(
            f"{runtime.opensandbox_url}/v1/sandboxes/{ids[0]}", headers=headers
        )
        assert info.status_code == 404, "Cancelled execution was not destroyed"

        config = ConnectionConfig(
            domain=runtime.opensandbox_url.split("://", 1)[1],
            protocol=runtime.opensandbox_url.split("://", 1)[0],
            api_key=runtime.opensandbox_api_key,
            use_server_proxy=True,
            disable_metrics=True,
        )
        expired = await create(
            runtime.opensandbox_image,
            connection_config=config,
            timeout=timedelta(seconds=60),
            ready_timeout=timedelta(seconds=5),
            metadata={"owner": "nexaflow-smoke", "purpose": "native-expiry"},
            network_policy=NetworkPolicy(
                default_action="deny",
                egress=[
                    NetworkRule(action="deny", target=target)
                    for target in DENIED_NETWORKS
                ],
            ),
            resource={"cpu": "1", "memory": "512Mi"},
        )
        try:
            await expired.close()  # Worker disappearance without destroy.
            async with asyncio.timeout(80):
                while True:
                    info = await client.get(
                        f"{runtime.opensandbox_url}/v1/sandboxes/{expired.id}",
                        headers=headers,
                    )
                    if info.status_code == 404:
                        break
                    info.raise_for_status()
                    await asyncio.sleep(5)
        finally:
            # Destroy only this test's sandbox if its expiry did not run.
            if info.status_code != 404:
                cleanup = await client.delete(
                    f"{runtime.opensandbox_url}/v1/sandboxes/{expired.id}",
                    headers=headers,
                )
                cleanup.raise_for_status()


async def run_checks(runtime) -> None:
    scope = execution_scope.set(
        ExecutionScope(
            "smoke-workspace", "smoke-invocation", "smoke-run", "smoke-worker"
        )
    )
    try:
        result = await execute_workflow_code(
            runtime, "result = inputs['value'] + 1", {"value": 2}
        )
        assert result.result == 3, result
        platform = OpenSandboxExecution(runtime)
        for path, code in (
            (
                "scripts/main.py",
                "import os, json, sys\nfrom pathlib import Path\np = Path(os.environ['NEXAFLOW_SKILL_DIR']) / 'assets/data.txt'\nassert p.read_text() == 'pinned'\ntry:\n p.write_text('tampered')\nexcept PermissionError:\n pass\nelse:\n raise AssertionError('Package was writable')\nprint(json.loads(sys.stdin.read())['value'] + 1)",
            ),
            (
                "scripts/main.js",
                "const fs = require('fs'); const input = JSON.parse(fs.readFileSync(0, 'utf8')); console.log(input.value + 1);",
            ),
        ):
            result = await platform.execute(
                {
                    "script": path,
                    "files": {
                        path: encoded(code),
                        "assets/data.txt": encoded("pinned"),
                    },
                    "stdin": '{"value": 2}',
                    "limits": {"timeout_ms": 5000},
                },
                timeout_seconds=6,
                max_output_bytes=10000,
            )
            assert result.get("ok") and result["stdout"].strip() == "3", result
        environment = "1" * 32
        session_script = "import smoke_dependency\nprint(smoke_dependency.VALUE)\n"
        installed = await platform.execute(
            {
                "execution_session": "agent_run",
                "skill_environment": environment,
                "files": {"scripts/session.py": encoded(session_script)},
                "shell": {
                    "manager": "python",
                    "command": (
                        "printf 'VALUE = 7\\n' > "
                        '"$NEXAFLOW_PYTHON_PACKAGES/smoke_dependency.py"'
                    ),
                    "bootstrap_id": "a" * 64,
                },
                "limits": {"timeout_ms": 5000},
            },
            timeout_seconds=6,
            max_output_bytes=10000,
        )
        assert installed.get("ok") and installed.get("environment_hash"), installed
        session_result = await platform.execute(
            {
                "execution_session": "agent_run",
                "skill_environment": environment,
                "script": "scripts/session.py",
                "files": {"scripts/session.py": encoded(session_script)},
                "limits": {"timeout_ms": 5000},
            },
            timeout_seconds=6,
            max_output_bytes=10000,
        )
        assert session_result.get("ok"), session_result
        assert session_result["stdout"].strip() == "7", session_result
        await assert_live_shell(platform)
        await platform.close_session("smoke-workspace", "smoke-run")
        probe = await platform.execute(
            {
                "code": "import os, json, socket\nassert not any(k in os.environ for k in ['DATABASE_URL', 'OPENSANDBOX_API_KEY', 'MODEL_SECRET_KEY', 'JWT_SECRET_KEY'])\nfor target in [('1.1.1.1', 443), ('169.254.169.254', 80)]:\n try:\n  socket.create_connection(target, timeout=0.3)\n except OSError:\n  pass\n else:\n  raise AssertionError('Unexpected egress')\nprint('isolated')",
                "limits": {"timeout_ms": 2000},
            },
            timeout_seconds=3,
            max_output_bytes=10000,
        )
        assert probe.get("ok") and probe["stdout"].strip() == "isolated", probe
        failed = await platform.execute(
            {"code": "while True: pass", "limits": {"timeout_ms": 200}},
            timeout_seconds=2,
            max_output_bytes=10000,
        )
        assert not failed.get("ok"), failed
        await assert_live_stdio_mcp(runtime)
        await assert_live_cleanup(runtime)
        print("OPENSANDBOX_SMOKE_OK")
    finally:
        await close_mcp_run_sessions("smoke-run")
        await OpenSandboxExecution(runtime).close_session(
            "smoke-workspace", "smoke-run"
        )
        execution_scope.reset(scope)


async def run(url: str, image: str, redis_url: str | None = None) -> None:
    runtime = replace(
        settings(),
        opensandbox_url=url,
        opensandbox_image=image,
        opensandbox_api_key=os.environ["OPENSANDBOX_API_KEY"],
    )
    async with isolated_run_store(runtime):
        await run_checks(runtime)
    if redis_url:
        await assert_live_pool_and_capacity(runtime, redis_url)


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--redis-url",
        help="Explicit isolated Redis for SDK pool and visitor capacity checks",
    )
    args = parser.parse_args()
    asyncio.run(run(args.url, args.image, args.redis_url))


if __name__ == "__main__":
    main()
