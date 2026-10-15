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
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import tests.support  # noqa: F401
from redis.exceptions import RedisError
from tests.support import settings

from app.adapters.execution import capacity
from app.adapters.execution import opensandbox as adapter
from app.adapters.mcp import client as mcp
from app.entities.defaults import utc_now
from app.entities.execution import ExecutionRun, ExecutionSession
from app.infra.execution.network import DENIED_NETWORKS, validate_egress_domain
from app.infra.execution.profile import execution_profile, require_execution_profile
from app.infra.sandbox import client
from app.infra.tools.mcp_stdio import parse_mcp_stdio_config
from app.ports.execution import (
    ExecutionBusy,
    ExecutionError,
    ExecutionNotStarted,
    ExecutionScope,
    execution_scope,
)
from app.ports.mcp import McpConnection, McpServerBusy


class FakeSessionStore:
    """Durable-store port double; real transaction checks live in sessions suite."""

    records = {}

    async def acquire(self, settings, scope, timeout, **kwargs):
        key = (
            scope.workspace_id,
            scope.run_id,
            kwargs.get("purpose", "run"),
            kwargs.get("owner_key", ""),
        )
        row = self.records.get(key)
        if row is None or row.state == "closed":
            row = ExecutionSession(
                workspace_id=scope.workspace_id,
                run_id=scope.run_id,
                expires_at=utc_now() + timedelta(seconds=300),
            )
            self.records[key] = row
        if row.holder:
            raise ExecutionBusy("Already held")
        row.holder = os.urandom(8).hex()
        return (
            deepcopy(row),
            ExecutionRun(row.expires_at, scope.worker_task_id, "console", ""),
            False,
            False,
        )

    def row(self, record):
        return next(row for row in self.records.values() if row.id == record.id)

    async def publish(self, record, *, scope=None, **values):
        row = self.row(record)
        if row.holder != record.holder:
            raise ExecutionBusy("Lease lost")
        for name, value in values.items():
            setattr(row, name, value)
            setattr(record, name, value)

    async def current(self, record, scope):
        row = self.row(record)
        return row.holder == record.holder and row.state in {"creating", "ready"}

    async def release(self, record):
        row = self.row(record)
        if row.holder == record.holder:
            row.holder = None

    async def closing(self, record, *, owned=False):
        row = self.row(record)
        if owned and row.holder != record.holder:
            return False
        row.state = "closing"
        return True

    async def closed(self, record):
        self.row(record).state = "closed"

    async def for_run(self, workspace_id, run_id):
        return [
            deepcopy(row)
            for row in self.records.values()
            if row.workspace_id == workspace_id
            and row.run_id == run_id
            and row.state != "closed"
        ]


class FakeRedis:
    """Evaluates the capacity scripts against an in-memory slot table."""

    slots: dict[str, int] = {}
    failure: Exception | None = None

    @classmethod
    def from_url(cls, *_args, **_kwargs):
        return cls()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return False

    async def eval(self, script, _numkeys, _key, *args):
        if self.failure is not None:
            raise self.failure
        if script is capacity._ACQUIRE:
            now, limit, expiry, token, _lifetime = args
            for held, score in list(self.slots.items()):
                if score <= now:
                    del self.slots[held]
            if len(self.slots) >= limit:
                return 0
            self.slots[token] = expiry
            return 1
        expiry, token, _lifetime = args
        self.slots[token] = expiry
        return 1

    async def zrem(self, _key, token):
        if self.failure is not None:
            raise self.failure
        self.slots.pop(token, None)


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
        close=AsyncMock(),
        renew=AsyncMock(),
        patch_egress_rules=AsyncMock(),
        delete_egress_rules=AsyncMock(),
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
    scope = execution_scope.set(ExecutionScope("tenant-a", invocation_id, "run/a"))

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
async def assert_agent_run_session_lifecycle():
    instance = sandbox()
    config = replace(
        runtime_settings(),
        opensandbox_egress_domains=("packages.example",),
    )
    platform = adapter.OpenSandboxExecution(config)
    scope = execution_scope.set(ExecutionScope("tenant-a", "install-1", "run-a"))
    try:
        with patch.object(
            adapter.Sandbox,
            "create",
            AsyncMock(return_value=instance),
        ) as create:
            first = await platform.execute(
                {
                    "execution_session": "agent_run",
                    "network_domains": ["packages.example"],
                    "shell": {
                        "manager": "python",
                        "command": "install",
                        "bootstrap_id": "a" * 64,
                    },
                },
                timeout_seconds=5,
                max_output_bytes=1000,
            )
            second = await platform.execute(
                {
                    "execution_session": "agent_run",
                    "code": "print(1)",
                },
                timeout_seconds=5,
                max_output_bytes=1000,
            )
            assert first == {"ok": True} and second == {"ok": True}
            assert create.await_count == 1
            instance.destroy.assert_not_awaited()
            instance.renew.assert_awaited()
            instance.patch_egress_rules.assert_awaited_once()
            rules = instance.patch_egress_rules.call_args.args[0]
            assert [(rule.action, rule.target) for rule in rules] == [
                ("allow", "packages.example")
            ]
            instance.delete_egress_rules.assert_awaited_once_with(["packages.example"])
            await platform.close_session("tenant-a", "run-a")
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
        except ExecutionNotStarted as exc:
            assert "secret" not in str(exc)
        else:
            raise AssertionError("Provider failure was accepted")
        config.close_transport_if_owned.assert_awaited_once()

    async def noisy(command, *, opts, handlers):
        await handlers.on_stdout(SimpleNamespace(text="x" * 4096))
        await handlers.on_stderr(SimpleNamespace(text="x" * 4097))

    for instance, request, started in (
        (sandbox(run=noisy), {}, True),
        (
            sandbox(
                run=AsyncMock(return_value=SimpleNamespace(error=None, exit_code=1))
            ),
            {},
            True,
        ),
        (sandbox(), {"files": {"../escape": "AA=="}}, False),
        (sandbox(), {"files": {"scripts/main.py": "invalid base64"}}, False),
    ):
        with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=instance)):
            try:
                await adapter.OpenSandboxExecution(runtime_settings()).execute(
                    request, timeout_seconds=5, max_output_bytes=1000
                )
            except ExecutionError as exc:
                assert isinstance(exc, ExecutionNotStarted) is not started
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
    assert json.loads(instance.files.entries[0].data)["files"] == {
        "scripts/main.py": ""
    }


@patch.object(adapter.OpenSandboxExecution, "_require_enforcement", new=AsyncMock())
async def assert_session_stages_packages_once():
    instance = sandbox()
    platform = adapter.OpenSandboxExecution(runtime_settings())
    environment = "a" * 32
    request = {
        "execution_session": "agent_run",
        "skill_environment": environment,
        "script": "scripts/main.py",
        "files": {"scripts/main.py": base64.b64encode(b"print(1)").decode()},
    }
    scope = execution_scope.set(ExecutionScope("tenant-a", "script-1", "run-stage"))
    try:
        with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=instance)):
            for _ in range(2):
                assert await platform.execute(
                    request, timeout_seconds=5, max_output_bytes=1000
                ) == {"ok": True}
            changed = {
                **request,
                "files": {"scripts/main.py": base64.b64encode(b"print(2)").decode()},
            }
            await platform.execute(changed, timeout_seconds=5, max_output_bytes=1000)
        paths = [entry.path for entry in instance.files.entries]
        package_path = f"/tmp/nexaflow-skill/{environment}/scripts/main.py"
        assert paths.count("/tmp/nexaflow-request.json") == 3
        assert paths.count(package_path) == 2
        await platform.close_session("tenant-a", "run-stage")
        instance.destroy.assert_awaited_once()
    finally:
        execution_scope.reset(scope)


@patch.object(adapter.OpenSandboxExecution, "_require_enforcement", new=AsyncMock())
async def assert_capacity_bounds_live_sandboxes():
    FakeRedis.slots = {}
    FakeRedis.failure = None
    platform = adapter.OpenSandboxExecution(
        replace(runtime_settings(), opensandbox_max_sandboxes=1)
    )
    held = sandbox()
    held.id = "sb-session"
    spare = sandbox()
    spare.id = "sb-spare"
    scope = execution_scope.set(ExecutionScope("tenant-a", "call-1", "run-capacity"))
    try:
        with (
            patch.object(capacity, "Redis", FakeRedis),
            patch.object(capacity, "ACQUIRE_WAIT_SECONDS", 0),
            patch.object(
                adapter.Sandbox, "create", AsyncMock(side_effect=[held, spare])
            ) as create,
        ):
            session_request = {"execution_session": "agent_run", "code": "print(1)"}
            await platform.execute(
                session_request, timeout_seconds=5, max_output_bytes=1000
            )
            FakeRedis.failure = RedisError("offline")
            await platform.execute(
                session_request, timeout_seconds=5, max_output_bytes=1000
            )
            FakeRedis.failure = None
            await platform.execute(
                session_request, timeout_seconds=5, max_output_bytes=1000
            )
            assert len(FakeRedis.slots) == 1
            try:
                await platform.execute(
                    {"code": "print(2)"}, timeout_seconds=5, max_output_bytes=1000
                )
            except ExecutionBusy:
                pass
            else:
                raise AssertionError("A sandbox was created beyond deployment capacity")
            assert create.await_count == 1
            FakeRedis.failure = RedisError("offline")
            await platform.close_session("tenant-a", "run-capacity")
            held.destroy.assert_awaited_once()
            # An unreleased slot is left to expire with the sandbox's TTL.
            assert len(FakeRedis.slots) == 1
            FakeRedis.failure = None
            FakeRedis.slots = {}
            assert await platform.execute(
                {"code": "print(2)"}, timeout_seconds=5, max_output_bytes=1000
            ) == {"ok": True}
            assert FakeRedis.slots == {}
            spare.destroy.assert_awaited_once()

            FakeRedis.failure = RedisError("offline")
            try:
                await platform.execute(
                    {"code": "print(3)"}, timeout_seconds=5, max_output_bytes=1000
                )
            except ExecutionNotStarted as exc:
                assert not isinstance(exc, ExecutionBusy)
            else:
                raise AssertionError("Capacity outage created an untracked sandbox")
            assert create.await_count == 2
    finally:
        FakeRedis.failure = None
        execution_scope.reset(scope)


@patch.object(adapter.OpenSandboxExecution, "_require_enforcement", new=AsyncMock())
async def assert_dependency_cache_and_missing_guest():
    digest = "a" * 64
    response = json.dumps(
        {"ok": True, "environment_hash": digest, "environment_lock": {"packages": []}}
    ).encode()
    first = sandbox(files=Files(response))
    replacement = sandbox(files=Files(response))
    replacement.id = "replacement-guest"
    platform = adapter.OpenSandboxExecution(runtime_settings())
    scope = execution_scope.set(ExecutionScope("tenant-cache", "install", "run-cache"))
    request = {
        "execution_session": "agent_run",
        "skill_environment": "b" * 32,
        "shell": {"bootstrap_id": "approved-install"},
        "expected_environment_hash": digest,
    }
    try:
        with (
            patch.object(
                adapter.Sandbox, "create", AsyncMock(side_effect=[first, replacement])
            ) as create,
            patch.object(
                adapter.Sandbox, "connect", AsyncMock(return_value=first)
            ) as connect,
        ):
            await platform.execute(request, timeout_seconds=10, max_output_bytes=1000)
            await platform.execute(request, timeout_seconds=10, max_output_bytes=1000)
            assert first.commands.run.await_count == 1, (
                "Reinstalled dependencies in the same guest"
            )
            record = (await platform.store.for_run("tenant-cache", "run-cache"))[0]
            row = platform.store.row(record)
            row.expires_at = row.expires_at.astimezone(timezone(timedelta(hours=8)))
            platform._sessions.pop(record.id)
            await first.close()
            await adapter.OpenSandboxExecution(runtime_settings()).execute(
                request, timeout_seconds=10, max_output_bytes=1000
            )
            connect.assert_awaited_once()
            assert 290 <= first.renew.call_args.args[0].total_seconds() <= 300, (
                "Database timezone extended the native TTL"
            )
            assert first.commands.run.await_count == 1, (
                "Lost the dependency cache after reconnecting"
            )
            missing = RuntimeError("guest removed")
            missing.status_code = 404
            first.renew.side_effect = missing
            result = await platform.execute(
                request, timeout_seconds=10, max_output_bytes=1000
            )
            assert result["workspace_reset"] and result["environment_hash"] == digest
            assert create.await_count == 2 and replacement.commands.run.await_count == 1
            # A different worker may have replaced the ID behind a cached handle.
            platform._sessions[record.id] = adapter._Session(first, row.expires_at)
            connect.return_value = replacement
            await platform.close_session("tenant-cache", "run-cache")
            replacement.destroy.assert_awaited_once()
    finally:
        execution_scope.reset(scope)


async def assert_failed_cleanup_keeps_capacity():
    platform = adapter.OpenSandboxExecution(runtime_settings())
    guest = sandbox()
    guest.destroy.side_effect = RuntimeError("control plane unavailable")
    platform.capacity.acquire = AsyncMock(return_value="reserved-slot")
    platform.capacity.release = AsyncMock()
    with (
        patch.object(adapter.Sandbox, "create", AsyncMock(return_value=guest)),
        patch.object(
            platform,
            "_require_enforcement",
            AsyncMock(side_effect=ExecutionError("unenforced")),
        ),
    ):
        try:
            await platform.execute({}, timeout_seconds=5, max_output_bytes=1000)
        except ExecutionNotStarted:
            pass
        else:
            raise AssertionError("Unenforced guest accepted")
    guest.destroy.assert_awaited_once()
    platform.capacity.release.assert_not_awaited()


async def assert_orphan_cleanup_respects_live_work():
    platform = adapter.OpenSandboxExecution(runtime_settings())
    platform.store.reclaimable = AsyncMock(return_value=[])
    platform.store.tracked = AsyncMock(
        return_value={"tracked-record": "tracked-guest", "creating-record": None}
    )

    def info(identifier, **metadata):
        return SimpleNamespace(
            id=identifier,
            created_at=utc_now() - timedelta(minutes=5),
            metadata={"owner": "nexaflow", **metadata},
        )

    manager = SimpleNamespace(
        list_sandbox_infos=AsyncMock(
            return_value=SimpleNamespace(
                sandbox_infos=[
                    info("tracked-guest"),
                    info("publishing-warm-guest", session="creating-record"),
                    info("live-ephemeral", purpose="ephemeral"),
                    info("orphan"),
                    info("old-pool", pool="obsolete-pool"),
                ],
                pagination=SimpleNamespace(has_next_page=False),
            )
        ),
        kill_sandbox=AsyncMock(),
        close=AsyncMock(),
    )
    with patch.object(
        adapter.SandboxManager, "create", AsyncMock(return_value=manager)
    ):
        await platform.reclaim_sessions()
        assert {call.args[0] for call in manager.kill_sandbox.await_args_list} == {
            "orphan",
            "old-pool",
        }
        manager.close.assert_awaited_once()
        manager.list_sandbox_infos.return_value.sandbox_infos = [
            info("foreign", owner="another-application")
        ]
        try:
            await platform.reclaim_sessions()
        except ExecutionError:
            pass
        else:
            raise AssertionError("Ignored owner filter was accepted")


@patch.object(adapter.OpenSandboxExecution, "_require_enforcement", new=AsyncMock())
async def assert_lease_loss_during_staging_never_starts_program():
    platform = adapter.OpenSandboxExecution(runtime_settings())

    class StagingFiles(Files):
        async def write_files(self, entries):
            await super().write_files(entries)
            platform.store.current = AsyncMock(return_value=False)

    guest = sandbox(files=StagingFiles())
    scope = execution_scope.set(ExecutionScope("fence-workspace", "late", "fence-run"))
    try:
        with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=guest)):
            try:
                await platform.execute(
                    {"execution_session": "agent_run", "code": "print(1)"},
                    timeout_seconds=10,
                    max_output_bytes=1000,
                )
            except ExecutionBusy:
                pass
            else:
                raise AssertionError("A lost lease was accepted")
        guest.commands.run.assert_not_awaited()
    finally:
        execution_scope.reset(scope)


@patch.object(adapter.OpenSandboxExecution, "_require_enforcement", new=AsyncMock())
async def assert_lost_mcp_owner_never_stages_secrets_or_starts_bridge():
    platform = adapter.OpenSandboxExecution(runtime_settings())
    platform.store.current = AsyncMock(return_value=False)
    guest = sandbox()
    scope = execution_scope.set(
        ExecutionScope("mcp-fence-workspace", "late", "mcp-fence-run")
    )
    try:
        with patch.object(adapter.Sandbox, "create", AsyncMock(return_value=guest)):
            try:
                async with platform.mcp_host(
                    {"command": "python", "env": {"TOKEN": "fixture"}},
                    [],
                    "registration",
                ):
                    raise AssertionError("A lost lease opened an MCP bridge")
            except ExecutionBusy:
                pass
        assert not guest.files.entries
        guest.commands.run.assert_not_awaited()
    finally:
        execution_scope.reset(scope)


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
            "mcp": {"content": [], "structuredContent": {"big": "中" * 21000}},
        }
        result = await mcp.call_mcp_tool(connection, settings(), "echo", {})
        assert result.structured_content is None
        assert result.meta == {"nexaflow/truncated": True}
        assert "Result truncated from" in result.content[0]["text"]
        assert (
            len(json.dumps(result.payload(), ensure_ascii=False).encode())
            <= mcp.MAX_MCP_RESULT_BYTES
        )

        for failure, expected, request_sent in (
            (ExecutionBusy("full"), McpServerBusy, False),
            (ExecutionNotStarted("create failed"), mcp.McpClientError, False),
            (ExecutionError("job failed"), mcp.McpClientError, True),
        ):
            platform.execute.side_effect = failure
            try:
                await mcp.call_mcp_tool(connection, settings(), "echo", {})
            except mcp.McpClientError as exc:
                assert isinstance(exc, expected)
                assert exc.request_sent is request_sent
            else:
                raise AssertionError("A failed stdio MCP call was accepted")
        platform.execute.side_effect = None


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
                assert not isinstance(exc, client.WorkflowSandboxBusyError)
                if "actionable" in invalid.get("stderr", ""):
                    assert str(exc) == "ValueError: actionable error"
            else:
                raise AssertionError("Invalid artifact envelope accepted")
        platform.execute.side_effect = ExecutionBusy("full")
        try:
            await client.execute_skill_artifact(
                settings(), "documents", {}, "txt", "result.txt"
            )
        except client.WorkflowSandboxBusyError:
            pass
        else:
            raise AssertionError("Exhausted sandbox capacity was not reported as busy")
        platform.execute.side_effect = None
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
        assert_agent_run_session_lifecycle,
        assert_failure_and_cancellation_cleanup,
        assert_platform_failure_boundaries,
        assert_immutable_package_staging,
        assert_session_stages_packages_once,
        assert_capacity_bounds_live_sandboxes,
        assert_dependency_cache_and_missing_guest,
        assert_failed_cleanup_keeps_capacity,
        assert_orphan_cleanup_respects_live_work,
        assert_lease_loss_during_staging_never_starts_program,
        assert_lost_mcp_owner_never_stages_secrets_or_starts_bridge,
        assert_stdio_dispatch,
        assert_workflow_port,
        assert_execution_response_contracts,
        assert_network_enforcement,
    ):
        with patch.object(adapter, "SessionStore", FakeSessionStore):
            asyncio.run(check())
    print("EXECUTION_UNIT_OK")


if __name__ == "__main__":
    main()
