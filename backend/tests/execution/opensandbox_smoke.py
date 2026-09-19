"""Opt-in real OpenSandbox checks against a dedicated test execution server.

Run from backend with OPENSANDBOX_API_KEY set; never uses the business database.
The server must already have the execution image and pinned execd/egress images.
"""

import argparse
import asyncio
import base64
import os
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import httpx
import tests.support  # noqa: F401
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models import NetworkPolicy, NetworkRule
from tests.support import settings

from app.adapters.execution.opensandbox import OpenSandboxExecution
from app.infra.execution.network import DENIED_NETWORKS
from app.infra.sandbox.client import execute_workflow_code
from app.infra.tools.mcp_stdio import parse_mcp_stdio_config
from app.ports.execution import ExecutionScope, execution_scope
from app.ports.mcp import McpConnection, call_mcp_tool, discover_mcp_tools


def encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


async def assert_live_stdio_mcp(runtime):
    source = (
        "import os\nfrom mcp.server.mcpserver import MCPServer\nfrom pydantic import BaseModel\n"
        "class Echo(BaseModel):\n value: str\n token: str\n business_env_absent: bool\n"
        "server = MCPServer('smoke', log_level='ERROR')\n"
        "@server.tool()\ndef echo(value: str) -> Echo:\n"
        " return Echo(value=value, token=os.environ['MCP_ONLY_TOKEN'], "
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
    }, result


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


async def run(url: str, image: str) -> None:
    runtime = replace(
        settings(),
        opensandbox_url=url,
        opensandbox_image=image,
        opensandbox_api_key=os.environ["OPENSANDBOX_API_KEY"],
    )
    scope = execution_scope.set(ExecutionScope("smoke-workspace", "smoke-invocation"))
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
        execution_scope.reset(scope)


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.image))


if __name__ == "__main__":
    main()
