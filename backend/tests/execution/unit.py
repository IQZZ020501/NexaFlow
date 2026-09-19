"""Pure execution port tests; no host processes, DB, Docker or network."""

import asyncio
import base64
import hashlib
import importlib.util
import io
import json
import os
import re
import tempfile
import tomllib
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import tests.support  # noqa: F401
from tests.support import settings

from app.adapters.execution import opensandbox as adapter
from app.adapters.mcp import client as mcp
from app.infra.execution.network import DENIED_NETWORKS, validate_egress_domain
from app.infra.execution.profile import execution_profile, require_execution_profile
from app.infra.sandbox import client
from app.infra.tools.mcp_stdio import parse_mcp_stdio_config
from app.ports.execution import ExecutionError, ExecutionScope, execution_scope
from app.ports.mcp import McpConnection


class Files:
    def __init__(self, value=b'{"ok":true}', chunks=None):
        self.value = value
        self.entries = []
        self.chunks = chunks

    async def write_files(self, entries):
        self.entries.extend(entries)

    async def read_bytes_stream(self, path):
        assert path == "/tmp/nexaflow-response.json"

        async def chunks():
            for value in self.chunks if self.chunks is not None else [self.value]:
                yield value

        return chunks()


def sandbox(files=None, run=None):
    return SimpleNamespace(
        id="sb-owned",
        files=files or Files(),
        destroy=AsyncMock(),
        commands=SimpleNamespace(
            run=run or AsyncMock(return_value=SimpleNamespace(error=None, exit_code=0))
        ),
    )


def runtime_settings():
    return replace(
        settings(),
        opensandbox_api_key="control-plane-test-key",
        opensandbox_image="execution:tested",
    )


@patch.object(adapter.OpenSandboxExecution, "_require_enforcement", new=AsyncMock())
async def assert_execution_lifecycle():
    instance = sandbox()
    invocation_id = "1:call_00_fqd8NnkrNewASPzvj2pb9371"
    scope = execution_scope.set(
        ExecutionScope("tenant-a", invocation_id, "run/a")
    )

    async def create_sandbox(*_args, **kwargs):
        for value in kwargs["metadata"].values():
            assert len(value) <= 63
            assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]", value)
        return instance

    try:
        with patch.object(
            adapter.Sandbox, "create", AsyncMock(side_effect=create_sandbox)
        ) as create:
            result = await adapter.OpenSandboxExecution(runtime_settings()).execute(
                {"code": "print(1)"}, timeout_seconds=5, max_output_bytes=1000
            )
            assert result == {"ok": True}
            kwargs = create.call_args.kwargs
            assert kwargs["metadata"]["workspace"] == "tenant-a"
            assert kwargs["metadata"]["invocation"] != invocation_id
            assert kwargs["metadata"]["invocation"].startswith("1-call_00_")
            assert kwargs["metadata"]["run"].startswith("run-a-")
            assert kwargs["timeout"].total_seconds() == 65
            assert kwargs["network_policy"].default_action == "deny"
            assert all(
                rule.action == "deny" for rule in kwargs["network_policy"].egress
            )
            assert {rule.target for rule in kwargs["network_policy"].egress} == set(
                DENIED_NETWORKS
            )
            assert kwargs["resource"] == {"cpu": "1", "memory": "512Mi"}
            assert "env" not in kwargs and "volumes" not in kwargs
            assert kwargs["connection_config"].use_server_proxy
            assert b"control-plane-test-key" not in instance.files.entries[0].data
            command = instance.commands.run.call_args
            assert command.kwargs["opts"].uid == 65532
            assert command.kwargs["opts"].timeout.total_seconds() == 5
            assert command.kwargs["handlers"].skip_accumulation
            instance.destroy.assert_awaited_once()
    finally:
        execution_scope.reset(scope)


@patch.object(adapter.OpenSandboxExecution, "_require_enforcement", new=AsyncMock())
async def assert_failure_and_cancellation_cleanup():
    for files in (
        Files(b"[]"),
        Files(b"invalid"),
        Files(chunks=[b"x" * 500, b"y" * 501]),
    ):
        instance = sandbox(files)
        with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=instance)):
            try:
                await adapter.OpenSandboxExecution(runtime_settings()).execute(
                    {}, timeout_seconds=5, max_output_bytes=1000
                )
            except ExecutionError:
                pass
            else:
                raise AssertionError("Invalid/oversized execution output accepted")
            instance.destroy.assert_awaited_once()
    ready = asyncio.Event()

    async def blocked(*args, **kwargs):
        ready.set()
        await asyncio.Event().wait()

    instance = sandbox(run=blocked)
    with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=instance)):
        task = asyncio.create_task(
            adapter.OpenSandboxExecution(runtime_settings()).execute(
                {}, timeout_seconds=5, max_output_bytes=1000
            )
        )
        await ready.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("Cancellation was swallowed")
        instance.destroy.assert_awaited_once()
    with patch.object(adapter.Sandbox, "create", AsyncMock()) as create:
        for config, request in (
            (replace(runtime_settings(), opensandbox_api_key=""), {}),
            (runtime_settings(), {"network_domains": ["unapproved.example"]}),
        ):
            try:
                await adapter.OpenSandboxExecution(config).execute(
                    request, timeout_seconds=5, max_output_bytes=1000
                )
            except ExecutionError:
                pass
            else:
                raise AssertionError("Unconfigured/unapproved execution accepted")
        create.assert_not_awaited()


@patch.object(adapter.OpenSandboxExecution, "_require_enforcement", new=AsyncMock())
async def assert_platform_failure_boundaries():
    with patch.object(adapter.Sandbox, "create", AsyncMock()) as create:
        try:
            await adapter.OpenSandboxExecution(runtime_settings()).execute(
                {"code": "x" * adapter.MAX_REQUEST_BYTES},
                timeout_seconds=5,
                max_output_bytes=1000,
            )
        except ExecutionError:
            pass
        else:
            raise AssertionError("Oversized input created a sandbox")
        create.assert_not_awaited()

    config = SimpleNamespace(close_transport_if_owned=AsyncMock())
    with (
        patch.object(adapter, "ConnectionConfig", return_value=config),
        patch.object(
            adapter.Sandbox,
            "create",
            AsyncMock(side_effect=RuntimeError("secret endpoint")),
        ),
    ):
        try:
            await adapter.OpenSandboxExecution(runtime_settings()).execute(
                {}, timeout_seconds=5, max_output_bytes=1000
            )
        except ExecutionError as exc:
            assert "secret" not in str(exc)
        else:
            raise AssertionError("Provider failure was accepted")
        config.close_transport_if_owned.assert_awaited_once()

    async def noisy(command, *, opts, handlers):
        await handlers.on_stdout(SimpleNamespace(text="x" * 4096))
        await handlers.on_stderr(SimpleNamespace(text="x" * 4097))

    for instance, request in (
        (sandbox(run=noisy), {}),
        (
            sandbox(
                run=AsyncMock(return_value=SimpleNamespace(error=None, exit_code=1))
            ),
            {},
        ),
        (sandbox(), {"files": {"../escape": "AA=="}}),
        (sandbox(), {"files": {"scripts/main.py": "invalid base64"}}),
    ):
        with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=instance)):
            try:
                await adapter.OpenSandboxExecution(runtime_settings()).execute(
                    request, timeout_seconds=5, max_output_bytes=1000
                )
            except ExecutionError:
                pass
            else:
                raise AssertionError("Invalid path/output/command was accepted")
            instance.destroy.assert_awaited_once()

    instance = sandbox()
    instance.destroy.side_effect = RuntimeError("cleanup failed")
    with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=instance)):
        assert await adapter.OpenSandboxExecution(runtime_settings()).execute(
            {}, timeout_seconds=5, max_output_bytes=1000
        ) == {"ok": True}
    await asyncio.sleep(0)  # Allow the cleanup exception-consumer callback to run.

    entered = asyncio.Event()
    release = asyncio.Event()

    async def destroy():
        entered.set()
        await release.wait()

    instance = sandbox()
    instance.destroy.side_effect = destroy
    with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=instance)):
        task = asyncio.create_task(
            adapter.OpenSandboxExecution(runtime_settings()).execute(
                {}, timeout_seconds=5, max_output_bytes=1000
            )
        )
        await entered.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("Cancellation during cleanup was swallowed")
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)


@patch.object(adapter.OpenSandboxExecution, "_require_enforcement", new=AsyncMock())
async def assert_immutable_package_staging():
    instance = sandbox()
    with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=instance)):
        await adapter.OpenSandboxExecution(runtime_settings()).execute(
            {"files": {"scripts/main.py": base64.b64encode(b"print(1)").decode()}},
            timeout_seconds=5,
            max_output_bytes=1000,
        )
    package = instance.files.entries[1]
    assert package.path == "/tmp/nexaflow-skill/scripts/main.py"
    assert package.owner == "root" and package.mode == 444


async def assert_stdio_dispatch():
    platform = SimpleNamespace(
        execute=AsyncMock(
            return_value={
                "ok": True,
                "mcp": {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]},
            }
        )
    )
    connection = McpConnection(
        transport="stdio",
        stdio_config=parse_mcp_stdio_config(
            {
                "command": "/image-only/bin/server",
                "env": {"ONLY_THIS_TOKEN": "integration-test"},
                "egress_domains": [],
            }
        ),
    )
    with patch.object(mcp, "build_execution_platform", return_value=platform):
        discovered = await mcp.discover_mcp_tools(connection, settings())
        assert discovered.tools[0]["name"] == "echo"
        request = platform.execute.call_args.args[0]
        assert request["mcp"]["config"]["env"] == {
            "ONLY_THIS_TOKEN": "integration-test"
        }
        assert request["network_domains"] == []
        platform.execute.return_value = {
            "ok": True,
            "mcp": {
                "content": [{"type": "text", "text": "hello"}],
                "structuredContent": {"answer": 1},
            },
        }
        result = await mcp.call_mcp_tool(connection, settings(), "echo", {}, "call-key")
        assert result.structured_content == {"answer": 1} and not result.is_error
        assert result.content == [{"type": "text", "text": "hello"}]
        assert (
            platform.execute.call_args.args[0]["mcp"]["meta"]["nexaflow/idempotencyKey"]
            == "call-key"
        )
        platform.execute.return_value = {
            "ok": True,
            "mcp": {"content": [], "structuredContent": {"big": "x" * 21000}},
        }
        try:
            await mcp.call_mcp_tool(connection, settings(), "echo", {})
        except mcp.McpClientError:
            pass
        else:
            raise AssertionError("MCP returned sliced, invalid JSON")


async def assert_workflow_port():
    platform = SimpleNamespace(
        execute=AsyncMock(
            return_value={
                "ok": True,
                "exit_code": 0,
                "stdout": 'log\n__NEXAFLOW_RESULT__={"result":{"value":3}}',
                "stderr": "",
            }
        )
    )
    with patch.object(client, "build_execution_platform", return_value=platform):
        result = await client.execute_workflow_code(
            settings(), "result = inputs", {"value": 3}
        )
        assert result.result == {"value": 3} and result.stdout == "log"
        assert json.loads(platform.execute.call_args.args[0]["stdin"]) == {"value": 3}
        platform.execute.side_effect = ExecutionError("offline")
        try:
            await client.execute_workflow_code(settings(), "result = 1", {})
        except client.WorkflowSandboxError:
            pass
        else:
            raise AssertionError("Offline platform executed on the host")


async def assert_execution_response_contracts():
    content = b"artifact"
    response = {
        "ok": True,
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "artifact": {
            "format": "txt",
            "filename": "result.txt",
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content_base64": base64.b64encode(content).decode(),
        },
    }
    platform = SimpleNamespace(execute=AsyncMock(return_value=response))
    with patch.object(client, "build_execution_platform", return_value=platform):
        assert (
            await client.execute_artifact_code(
                settings(), "pass", "txt", "result.txt", ["documents"]
            )
        ).content == content
        assert (
            await client.execute_skill_artifact(
                settings(), "documents", {"title": "test"}, "txt", "result.txt"
            )
        ).content == content
        for invalid in (
            {},
            {**response, "artifact": None},
            {**response, "artifact": {**response["artifact"], "content_base64": "bad"}},
            {**response, "artifact": {**response["artifact"], "sha256": "0" * 64}},
            {**response, "error": "sandbox_busy", "ok": False},
            {
                **response,
                "ok": False,
                "stderr": "Traceback\n  detail\nValueError: actionable error",
            },
        ):
            platform.execute.return_value = invalid
            try:
                await client.execute_skill_artifact(
                    settings(), "documents", {}, "txt", "result.txt"
                )
            except client.WorkflowSandboxError as exc:
                if invalid.get("error") == "sandbox_busy":
                    assert isinstance(exc, client.WorkflowSandboxBusyError)
                if "actionable" in invalid.get("stderr", ""):
                    assert str(exc) == "ValueError: actionable error"
            else:
                raise AssertionError("Invalid artifact envelope accepted")
        for stdout in (
            "no marker",
            client.RESULT_MARKER + "bad",
            client.RESULT_MARKER + "[]",
        ):
            platform.execute.return_value = {
                "ok": True,
                "exit_code": 0,
                "stdout": stdout,
            }
            try:
                await client.execute_workflow_code(
                    settings(), "pass", {}, ["documents"]
                )
            except client.WorkflowSandboxError:
                pass
            else:
                raise AssertionError("Invalid workflow result accepted")
        platform.execute.side_effect = ValueError("provider malformed JSON")
        try:
            await client.execute_workflow_code(settings(), "pass", {})
        except client.WorkflowSandboxError:
            pass
        else:
            raise AssertionError("Malformed provider response accepted")


def assert_private_server_configuration():
    spec = importlib.util.spec_from_file_location(
        "execution_configure",
        Path(__file__).resolve().parents[3] / "deploy/opensandbox/configure.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix="nexaflow-config-test-") as directory:
        state = Path(directory)
        config = tomllib.loads(
            module.server_config(state, 'fixture-"quoted"', development=False)
        )
        assert config["server"]["api_key"] == 'fixture-"quoted"'
        assert config["secure_runtime"] == {
            "type": "kata",
            "docker_runtime": "kata-runtime",
        }
        assert config["egress"]["mode"] == "dns+nft"
        assert config["storage"]["allowed_host_paths"] == []
        assert (
            config["docker"]["sandbox_env"] == {}
            and config["docker"]["sandbox_binds"] == []
        )
        assert "secure_runtime" not in tomllib.loads(
            module.server_config(state, "fixture", development=True)
        )
        arguments = ["configure.py", "--state-dir", str(state)]
        with (
            patch.object(module.sys, "argv", arguments),
            patch.dict(os.environ, {"OPENSANDBOX_API_KEY": "fixture"}),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            module.main()
            target = state / "server.toml"
            assert target.stat().st_mode & 0o777 == 0o600
            before = target.read_bytes()
            try:
                module.main()
            except SystemExit as exc:
                assert exc.code == 2
            else:
                raise AssertionError("Existing operator configuration was overwritten")
            assert target.read_bytes() == before
        for arguments, key in (
            (["configure.py", "--state-dir", "/"], "fixture"),
            (["configure.py", "--state-dir", str(state / "missing-key")], ""),
        ):
            with (
                patch.object(module.sys, "argv", arguments),
                patch.dict(os.environ, {"OPENSANDBOX_API_KEY": key}),
                redirect_stderr(io.StringIO()),
            ):
                try:
                    module.main()
                except SystemExit as exc:
                    assert exc.code == 2
                else:
                    raise AssertionError("Unsafe/unconfigured execution host accepted")


async def assert_network_enforcement():
    instance = sandbox()
    instance.get_endpoint = AsyncMock(
        return_value=SimpleNamespace(headers={"OPENSANDBOX-EGRESS-AUTH": "test"})
    )
    valid = {
        "enforcementMode": "dns+nft",
        "policy": {
            "defaultAction": "deny",
            "egress": [
                {"action": "deny", "target": target} for target in DENIED_NETWORKS
            ],
        },
    }
    original_client = httpx.AsyncClient
    for status in (
        valid,
        {**valid, "enforcementMode": "dns"},
        {**valid, "policy": {"defaultAction": "allow"}},
        {
            **valid,
            "policy": {
                **valid["policy"],
                "egress": [
                    *valid["policy"]["egress"],
                    {"action": "allow", "target": "unapproved.example"},
                ],
            },
        },
    ):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=status)
        )
        with patch.object(
            adapter.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: original_client(transport=transport, **kwargs),
        ):
            try:
                await adapter.OpenSandboxExecution(
                    runtime_settings()
                )._require_enforcement(instance, [])
            except ExecutionError:
                assert status is not valid
            else:
                assert status is valid
    for domain in (
        "127.0.0.1",
        "localhost",
        "metadata.google.internal",
        "*.local",
        "a..com",
        "https://api.example.com",
    ):
        try:
            validate_egress_domain(domain)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid execution domain accepted")
    assert validate_egress_domain("*.Example.COM") == "*.example.com"


def main():
    assert_private_server_configuration()
    original = runtime_settings()
    profile = execution_profile(original)
    require_execution_profile(replace(original, opensandbox_api_key="rotated"), profile)
    assert "control-plane-test-key" not in json.dumps(profile)
    for changed in (
        replace(original, opensandbox_image="different-image"),
        replace(original, opensandbox_egress_domains=("approved.example",)),
    ):
        try:
            require_execution_profile(changed, profile)
        except ValueError:
            pass
        else:
            raise AssertionError("A retried run used a different execution profile")
    for check in (
        assert_execution_lifecycle,
        assert_failure_and_cancellation_cleanup,
        assert_platform_failure_boundaries,
        assert_immutable_package_staging,
        assert_stdio_dispatch,
        assert_workflow_port,
        assert_execution_response_contracts,
        assert_network_enforcement,
    ):
        asyncio.run(check())
    print("EXECUTION_UNIT_OK")


if __name__ == "__main__":
    main()
