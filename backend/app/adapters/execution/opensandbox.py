"""OpenSandbox lifecycle, bounded I/O and cancellation in one private adapter."""

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
from collections.abc import Hashable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from urllib.parse import urlparse
from uuid import uuid4
from weakref import WeakValueDictionary

import httpx
from opensandbox import Sandbox, SandboxManager
from opensandbox.config import ConnectionConfig
from opensandbox.models import NetworkPolicy, NetworkRule, SandboxFilter, WriteEntry
from opensandbox.models.execd import ExecutionHandlers, RunCommandOpts
from opensandbox.transport import RetryPolicy

from app.adapters.execution import pool
from app.adapters.execution.capacity import SandboxCapacity
from app.adapters.execution.resources import RESOURCES, request_profile
from app.infra.config.settings import Settings
from app.infra.execution.network import DENIED_NETWORKS, validate_egress_domain
from app.infra.execution.sessions import SessionStore
from app.ports.execution import (
    ExecutionBridge,
    ExecutionBusy,
    ExecutionError,
    ExecutionNotStarted,
    execution_scope,
)

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_METADATA_LABEL_LENGTH = 63
_INVALID_METADATA_LABEL_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_UNAVAILABLE = "OpenSandbox execution is unavailable or failed."


def _metadata_label(value: str) -> str:
    if (
        0 < len(value) <= MAX_METADATA_LABEL_LENGTH
        and value[0].isascii()
        and value[0].isalnum()
        and value[-1].isascii()
        and value[-1].isalnum()
        and _INVALID_METADATA_LABEL_CHARS.search(value) is None
    ):
        return value
    normalized = _INVALID_METADATA_LABEL_CHARS.sub("-", value).strip("._-")
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    prefix_length = MAX_METADATA_LABEL_LENGTH - len(digest) - 1
    prefix = normalized[:prefix_length].rstrip("._-") or "value"
    return f"{prefix}-{digest}"


def _utc_time(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


class _Session:
    """A Run-private sandbox and the immutable packages already staged in it."""

    def __init__(self, sandbox, expires_at) -> None:
        self.sandbox = sandbox
        self.expires_at = expires_at


class OpenSandboxExecution:
    _sessions: dict[str, _Session] = {}
    _session_locks: WeakValueDictionary[tuple[Hashable, ...], asyncio.Lock] = (
        WeakValueDictionary()
    )
    _capacity_slots: dict[str, str] = {}
    _consumer_slots: dict[str, str | None] = {}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.capacity = SandboxCapacity(settings)
        self.store = SessionStore()

    async def execute(self, request, *, timeout_seconds, max_output_bytes):
        settings = self.settings
        if not settings.opensandbox_api_key or not settings.opensandbox_image:
            raise ExecutionNotStarted(
                "OpenSandbox is not configured; local execution is disabled."
            )
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False).encode()
        if len(payload) > MAX_REQUEST_BYTES:
            raise ExecutionNotStarted("Execution input exceeds 8 MiB.")
        await self._close_expired_handles()
        scope = execution_scope.get()
        domains = self._network_domains(request)
        session_key = self._session_key(request, scope)
        if session_key is None:
            sandbox = await self._create_sandbox(
                scope,
                domains,
                timeout_seconds,
                persistent=False,
                profile=request_profile(request),
            )
            try:
                return await self._run_request(
                    sandbox,
                    request,
                    timeout_seconds,
                    max_output_bytes,
                )
            finally:
                await self._destroy_sandbox(sandbox)

        lock = self._session_locks.setdefault(session_key, asyncio.Lock())
        async with lock:
            record, run, reset, stale = await self.store.acquire(
                self.settings, scope, timeout_seconds
            )
            sandbox = None
            try:

                async def perform():
                    nonlocal sandbox, reset
                    sandbox, reset = await self._connect_record(
                        record, scope, timeout_seconds, reset, run.resource_profile
                    )
                    if stale:
                        await self._stop_stale_processes(sandbox)
                    if not await self.store.current(record, scope):
                        raise ExecutionBusy("Run sandbox lease was lost.")
                    if domains:
                        await self._allow_egress(sandbox, domains)
                    else:
                        await self._require_enforcement(sandbox, [])
                    response = await self._execute_record(
                        sandbox,
                        record,
                        request,
                        timeout_seconds,
                        max_output_bytes,
                    )
                    if domains:
                        await sandbox.delete_egress_rules(domains)
                        await self._require_enforcement(sandbox, [])
                    return response

                response = await self._fenced(record, scope, perform())
                if reset:
                    response["workspace_reset"] = True
                return response
            except BaseException:
                # A worker that lost the holder cannot destroy its successor's guest.
                if sandbox is not None and await self.store.closing(record, owned=True):
                    self._sessions.pop(record.id, None)
                    if await self._destroy_sandbox(sandbox):
                        await self.store.closed(record)
                raise
            finally:
                await self.store.release(record)

    async def _execute_record(self, sandbox, record, request, timeout, max_bytes):
        staged = set(record.staged_packages)
        shell = request.get("shell")
        environment_key = None
        if shell:
            environment_key = (
                f"{request.get('skill_environment', '')}:{shell['bootstrap_id']}"
            )
            installed = record.environments.get(environment_key)
            expected = request.get("expected_environment_hash")
            if installed and (
                expected is None or expected == installed.get("environment_hash")
            ):
                return {
                    "ok": True,
                    "stdout": "",
                    "stderr": "",
                    "exit_code": 0,
                    **installed,
                }
        response = await self._run_request(
            sandbox, request, timeout, max_bytes, staged=staged, record=record
        )
        environments = dict(record.environments)
        if environment_key and response.get("ok") and response.get("environment_hash"):
            environments[environment_key] = {
                key: response[key] for key in ("environment_hash", "environment_lock")
            }
        await self.store.publish(
            record,
            scope=execution_scope.get(),
            staged_packages=sorted(staged),
            environments=environments,
        )
        return response

    async def _connect_record(
        self, record, scope, timeout, reset=False, profile="standard"
    ):
        cached = self._sessions.get(record.id)
        sandbox = (
            cached.sandbox
            if cached and cached.sandbox.id == record.sandbox_id
            else None
        )
        if cached is not None and sandbox is None:
            await cached.sandbox.close()
        lifetime = max(
            1,
            (_utc_time(record.expires_at) - datetime.now(UTC)).total_seconds(),
        )
        if record.sandbox_id:
            try:
                if sandbox is None:
                    sandbox = await Sandbox.connect(
                        record.sandbox_id,
                        connection_config=self._connection_config(timeout),
                    )
                await sandbox.renew(timedelta(seconds=lifetime))
            except Exception as exc:
                # Do not turn a transient control-plane outage into a second guest.
                status = getattr(exc, "status_code", None) or getattr(
                    getattr(exc, "response", None), "status_code", None
                )
                if status != 404:
                    raise ExecutionNotStarted(_UNAVAILABLE) from exc
                if sandbox is not None:
                    await sandbox.close()
                self._sessions.pop(record.id, None)
                self._capacity_slots.pop(record.sandbox_id, None)
                self._consumer_slots.pop(record.sandbox_id, None)
                await self.capacity.release(record.capacity_token, record.consumer_key)
                sandbox = None
                reset = True
        if sandbox is None:
            sandbox = await self._create_sandbox(
                scope,
                [],
                timeout,
                persistent=True,
                lifetime=lifetime,
                profile=profile,
                consumer_key=record.consumer_key,
                session_id=record.id,
            )
            try:
                await self.store.publish(
                    record,
                    scope=scope,
                    sandbox_id=sandbox.id,
                    state="ready",
                    capacity_token=self._capacity_slots.get(sandbox.id),
                    staged_packages=[],
                    environments={},
                )
            except BaseException:
                await self._destroy_sandbox(sandbox)
                raise
        else:
            await self.capacity.renew(
                record.capacity_token, lifetime, record.consumer_key
            )
            if record.capacity_token:
                self._capacity_slots[sandbox.id] = record.capacity_token
                self._consumer_slots[sandbox.id] = record.consumer_key
        self._sessions[record.id] = _Session(sandbox, record.expires_at)
        return sandbox, reset

    async def _close_expired_handles(self):
        now = datetime.now(UTC)
        for key, cached in list(self._sessions.items()):
            if _utc_time(cached.expires_at) <= now:
                self._sessions.pop(key, None)
                self._capacity_slots.pop(cached.sandbox.id, None)
                self._consumer_slots.pop(cached.sandbox.id, None)
                await cached.sandbox.close()

    async def _fenced(self, record, scope, operation):
        async def watch():
            while True:
                await asyncio.sleep(2)
                if not await self.store.current(record, scope):
                    raise ExecutionBusy("Run sandbox lease was lost.")

        task = asyncio.create_task(operation)
        guard = asyncio.create_task(watch())
        try:
            done, _ = await asyncio.wait(
                (task, guard), return_when=asyncio.FIRST_COMPLETED
            )
            if guard in done:
                await guard
            response = await task
            if not await self.store.current(record, scope):
                raise ExecutionBusy("Run sandbox lease was lost.")
            return response
        finally:
            for pending in (task, guard):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, guard, return_exceptions=True)

    async def _stop_stale_processes(self, sandbox):
        result = await sandbox.commands.run(
            "/opt/nexaflow/.venv/bin/python -I /opt/nexaflow/command.py --stop-stale",
            opts=RunCommandOpts(timeout=timedelta(seconds=10), uid=0, gid=0),
        )
        if result.error or result.exit_code not in (None, 0):
            raise ExecutionError("Previous sandbox command could not be stopped.")

    def _network_domains(self, request) -> list[str]:
        domains = request.get("network_domains", [])
        if not isinstance(domains, list) or any(
            not isinstance(domain, str)
            or domain not in self.settings.opensandbox_egress_domains
            for domain in domains
        ):
            raise ExecutionNotStarted(
                "Execution egress exceeds the deployment allowlist."
            )
        try:
            for domain in domains:
                validate_egress_domain(domain)
        except ValueError as exc:
            raise ExecutionNotStarted(str(exc)) from exc
        return list(dict.fromkeys(domains))

    def _session_key(self, request, scope):
        session_scope = request.get("execution_session")
        if session_scope is None:
            return None
        if session_scope != "agent_run" or scope is None or not scope.run_id:
            raise ExecutionNotStarted("Agent Run execution session is unavailable.")
        return (
            self.settings.opensandbox_url,
            self.settings.opensandbox_image,
            scope.workspace_id,
            scope.run_id,
        )

    def _lifetime_seconds(self, timeout_seconds, *, persistent) -> float:
        # Native TTL also reclaims executions after worker death or kill failure.
        return max(
            60,
            (
                self.settings.agent_run_timeout_seconds + 60
                if persistent
                else timeout_seconds + 60
            ),
        )

    def _connection_config(self, timeout_seconds):
        endpoint = urlparse(self.settings.opensandbox_url)
        return ConnectionConfig(
            domain=endpoint.netloc + endpoint.path.rstrip("/"),
            protocol=endpoint.scheme,
            api_key=self.settings.opensandbox_api_key,
            use_server_proxy=True,
            request_timeout=timedelta(seconds=timeout_seconds + 30),
            retry_policy=RetryPolicy.disabled(),
            disable_metrics=True,
        )

    async def _create_sandbox(
        self,
        scope,
        domains,
        timeout_seconds,
        *,
        persistent,
        lifetime=None,
        profile="small",
        consumer_key=None,
        session_id=None,
    ):
        settings = self.settings
        lifetime = lifetime or self._lifetime_seconds(
            timeout_seconds, persistent=persistent
        )
        slot = await self.capacity.acquire(lifetime, consumer_key)
        config = self._connection_config(timeout_seconds)
        sandbox = None
        metadata = {
            "owner": "nexaflow",
            "execution": str(uuid4()),
            "purpose": "run" if persistent else "ephemeral",
        }
        if session_id is not None:
            metadata["session"] = session_id
        if scope:
            metadata.update(
                workspace=_metadata_label(scope.workspace_id),
                invocation=_metadata_label(scope.invocation_id),
            )
            if scope.run_id:
                metadata["run"] = _metadata_label(scope.run_id)
        try:
            sandbox = await pool.acquire(self, profile, lifetime)
            if sandbox is not None:
                self._capacity_slots[sandbox.id] = slot
                self._consumer_slots[sandbox.id] = consumer_key
                await sandbox.patch_metadata({**metadata, "pool": ""})
                if domains:
                    await self._allow_egress(sandbox, domains)
            else:
                sandbox = await Sandbox.create(
                    settings.opensandbox_image,
                    connection_config=config,
                    metadata=metadata,
                    timeout=timedelta(seconds=lifetime),
                    ready_timeout=timedelta(seconds=30),
                    resource=RESOURCES[profile],
                    network_policy=NetworkPolicy(
                        default_action="deny",
                        egress=[
                            *(
                                NetworkRule(action="deny", target=cidr)
                                for cidr in DENIED_NETWORKS
                            ),
                            *(
                                NetworkRule(action="allow", target=domain)
                                for domain in domains
                            ),
                        ],
                    ),
                )
                self._capacity_slots[sandbox.id] = slot
                self._consumer_slots[sandbox.id] = consumer_key
            await self._require_enforcement(sandbox, domains)
        except BaseException as exc:
            if sandbox is not None:
                await self._destroy_sandbox(sandbox)
            else:
                await config.close_transport_if_owned()
                await self.capacity.release(slot, consumer_key)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ExecutionNotStarted(_UNAVAILABLE) from exc
        return sandbox

    async def _allow_egress(self, sandbox, domains) -> None:
        try:
            await sandbox.patch_egress_rules(
                [NetworkRule(action="allow", target=domain) for domain in domains]
            )
            await self._require_enforcement(sandbox, domains)
        except ExecutionError as exc:
            raise ExecutionNotStarted(str(exc)) from exc
        except Exception as exc:
            raise ExecutionNotStarted(_UNAVAILABLE) from exc

    def _package_entries(self, request) -> tuple[str, list[WriteEntry]]:
        environment = request.get("skill_environment")
        if environment is not None and (
            not isinstance(environment, str)
            or re.fullmatch(r"[a-f0-9]{32}", environment) is None
        ):
            raise ExecutionNotStarted("Invalid Skill environment.")
        package_root = (
            f"/tmp/nexaflow-skill/{environment}"
            if environment is not None
            else "/tmp/nexaflow-skill"
        )
        files = request.get("files", {})
        if not isinstance(files, dict):
            raise ExecutionNotStarted("Invalid execution package.")
        entries = []
        for name, encoded in files.items():
            if (
                not isinstance(name, str)
                or PurePosixPath(name).is_absolute()
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or "\\" in name
                or ":" in name
            ):
                raise ExecutionNotStarted("Invalid execution package path.")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (TypeError, ValueError) as exc:
                raise ExecutionNotStarted("Invalid execution package content.") from exc
            entries.append(
                WriteEntry(
                    path=f"{package_root}/{name}",
                    data=data,
                    mode=444,
                    owner="root",
                    group="root",
                )
            )
        digest = hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return f"{package_root}:{digest}", entries

    async def _run_request(
        self,
        sandbox,
        request,
        timeout_seconds,
        max_output_bytes,
        *,
        staged: set[str] | None = None,
        record=None,
    ):
        package_key, entries = self._package_entries(request)
        if staged is not None and package_key in staged:
            entries = []
        package_pending = bool(entries)
        mounted = request.get("skill_mounts", {})
        if not isinstance(mounted, dict):
            raise ExecutionNotStarted("Invalid Skill mounts.")
        for name, files in mounted.items():
            if not isinstance(name, str) or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,63}", name
            ):
                raise ExecutionNotStarted("Invalid Skill mount name.")
            mount_key, mount_entries = self._package_entries({"files": files})
            mount_key = f"/skills/{name}:{mount_key}"
            if staged is None or mount_key not in staged:
                entries.extend(
                    WriteEntry(
                        path=entry.path.replace(
                            "/tmp/nexaflow-skill/", f"/skills/{name}/", 1
                        ),
                        data=entry.data,
                        mode=444,
                        owner="root",
                        group="root",
                    )
                    for entry in mount_entries
                )
                if staged is not None:
                    staged.add(mount_key)
        files = request.get("files", {})
        # Package contents are staged as root-owned files; job.py only needs
        # their names, so a reused session does not upload them again.
        job_request = (
            {**request, "files": dict.fromkeys(files, "")} if files else request
        )
        job_request = {
            key: value for key, value in job_request.items() if key != "skill_mounts"
        }
        command_mode = "command" in request
        protocol = (
            f"/tmp/nexaflow-protocol/{uuid4().hex}" if command_mode else "/tmp/nexaflow"
        )
        request_path, response_path = (
            f"{protocol}-request.json",
            f"{protocol}-response.json",
        )
        if record is not None and not await self.store.current(
            record, execution_scope.get()
        ):
            raise ExecutionBusy("Run sandbox lease was lost.")
        try:
            await sandbox.files.write_files(
                [
                    WriteEntry(
                        path=request_path,
                        data=json.dumps(
                            job_request, ensure_ascii=False, allow_nan=False
                        ).encode(),
                        mode=400,
                        owner="root" if command_mode else "nexaflow",
                        group="root" if command_mode else "nexaflow",
                    )
                ]
            )
            if entries:
                await sandbox.files.write_files(entries)
                if staged is not None and package_pending:
                    staged.add(package_key)
        except Exception as exc:
            raise ExecutionNotStarted(_UNAVAILABLE) from exc
        count = 0

        async def bound_output(message):
            nonlocal count
            count += len(message.text.encode())
            if count > 8192:
                raise ExecutionError("Execution command output exceeds its limit.")

        async with asyncio.timeout(timeout_seconds + 5):
            if record is not None and not await self.store.current(
                record, execution_scope.get()
            ):
                raise ExecutionBusy("Run sandbox lease was lost.")
            result = await sandbox.commands.run(
                f"/opt/nexaflow/.venv/bin/python -I /opt/nexaflow/job.py {request_path} {response_path}",
                opts=RunCommandOpts(
                    timeout=timedelta(seconds=timeout_seconds),
                    uid=0 if command_mode else 65532,
                    gid=0 if command_mode else 65532,
                ),
                handlers=ExecutionHandlers(
                    on_stdout=bound_output,
                    on_stderr=bound_output,
                    skip_accumulation=True,
                ),
            )
            if result.error or result.exit_code not in (None, 0):
                raise ExecutionError("OpenSandbox execution failed.")
            content = bytearray()
            stream = await sandbox.files.read_bytes_stream(response_path)
            async for chunk in stream:
                content.extend(chunk)
                if len(content) > max_output_bytes:
                    raise ExecutionError("Execution output exceeds its limit.")
            try:
                value = json.loads(content)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ExecutionError(
                    "OpenSandbox returned an invalid response."
                ) from exc
            if not isinstance(value, dict):
                raise ExecutionError("OpenSandbox returned an invalid response.")
            return value

    async def close_session(self, workspace_id: str, run_id: str) -> None:
        for record in await self.store.for_run(workspace_id, run_id):
            await self._close_record(record)

    @asynccontextmanager
    async def mcp_host(self, config, domains, owner_key):
        scope = execution_scope.get()
        if not scope or not scope.run_id:
            raise ExecutionNotStarted("MCP hosting requires a Run scope.")
        self._network_domains({"network_domains": domains})
        record, _, _, _ = await self.store.acquire(
            self.settings, scope, 60, purpose="mcp", owner_key=owner_key
        )
        sandbox = None
        watcher = None
        try:
            # Credentials live only in the owner process. A restarted owner
            # retires the previous guest before starting a fresh bridge.
            if record.sandbox_id:
                await self._close_record(record, owned=True)
                record, _, _, _ = await self.store.acquire(
                    self.settings, scope, 60, purpose="mcp", owner_key=owner_key
                )
            sandbox, _ = await self._connect_record(
                record, scope, 60, profile="standard"
            )
            if domains:
                await self._allow_egress(sandbox, domains)
            else:
                await self._require_enforcement(sandbox, [])
            if not await self.store.current(record, scope):
                raise ExecutionBusy("MCP host lease was lost.")
            token = secrets.token_urlsafe(32)
            await sandbox.files.write_files(
                [
                    WriteEntry(
                        path="/tmp/nexaflow-mcp-bridge.json",
                        data=json.dumps(
                            {"config": config, "token": token}, ensure_ascii=False
                        ).encode(),
                        mode=400,
                        owner="nexaflow",
                        group="nexaflow",
                    )
                ]
            )
            if not await self.store.current(record, scope):
                raise ExecutionBusy("MCP host lease was lost.")
            result = await sandbox.commands.run(
                "/opt/nexaflow/.venv/bin/python -I /opt/nexaflow/mcp_bridge.py /tmp/nexaflow-mcp-bridge.json",
                opts=RunCommandOpts(background=True, uid=65532, gid=65532),
            )
            if result.error:
                raise ExecutionNotStarted("MCP bridge could not start.")
            base = f"{self.settings.opensandbox_url.rstrip('/')}/v1/sandboxes/{sandbox.id}/proxy/18081"
            headers = {
                "OPEN-SANDBOX-API-KEY": self.settings.opensandbox_api_key,
                "X-NexaFlow-MCP-Token": f"Bearer {token}",
            }
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=False, timeout=3
            ) as client:
                async with asyncio.timeout(45):
                    while True:
                        if not await self.store.current(record, scope):
                            raise ExecutionBusy("MCP host lease was lost.")
                        try:
                            ready = await client.get(f"{base}/health", headers=headers)
                            if (
                                ready.status_code == 200
                                and ready.json().get("ready") is True
                            ):
                                break
                        except (httpx.HTTPError, ValueError):
                            pass
                        await asyncio.sleep(0.2)
            owner = asyncio.current_task()

            async def watch():
                try:
                    while True:
                        await asyncio.sleep(2)
                        if not await self.store.current(record, scope):
                            break
                except Exception:
                    pass
                owner.cancel()

            watcher = asyncio.create_task(watch())
            yield ExecutionBridge(f"{base}/mcp", headers)
        finally:
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            if sandbox is not None:
                await self._close_record(record, owned=True)
            await self.store.release(record)

    async def reclaim_sessions(self) -> None:
        if not self.settings.opensandbox_api_key:
            return
        for record in await self.store.reclaimable():
            await self._close_record(record)
        tracked = await self.store.tracked()
        manager = await SandboxManager.create(
            connection_config=self._connection_config(10)
        )
        try:
            page = 1
            orphans = []
            while True:
                result = await manager.list_sandbox_infos(
                    SandboxFilter(
                        metadata={"owner": "nexaflow"}, page=page, page_size=100
                    )
                )
                for info in result.sandbox_infos:
                    metadata = info.metadata or {}
                    if metadata.get("owner") != "nexaflow":
                        raise ExecutionError(
                            "Control plane ignored the sandbox owner filter."
                        )
                    # Creation/publish is not atomic across the DB and control plane.
                    if (
                        info.id not in tracked.values()
                        and not (
                            metadata.get("session") in tracked
                            and tracked[metadata["session"]] is None
                        )
                        and metadata.get("purpose") != "ephemeral"
                        and metadata.get("pool")
                        not in pool.current_pool_names(self.settings)
                        and (datetime.now(UTC) - info.created_at).total_seconds() > 120
                    ):
                        orphans.append((info.id, metadata.get("session")))
                if not result.pagination.has_next_page:
                    break
                page += 1
            # An acquired warm guest can be old while its new DB owner is still
            # publishing; refresh before deletion and honor creating intents.
            tracked = await self.store.tracked()
            for sandbox_id, session_id in orphans:
                if sandbox_id not in tracked.values() and not (
                    session_id in tracked and tracked[session_id] is None
                ):
                    await manager.kill_sandbox(sandbox_id)
        finally:
            await manager.close()

    async def read_session_file(self, workspace_id, run_id, path, max_bytes):
        if (
            not isinstance(path, str)
            or re.fullmatch(r"/tmp/nexaflow-exports/[a-f0-9]{32}/[0-7]", path) is None
            or type(max_bytes) is not int
            or not 0 < max_bytes <= 5 * 1024 * 1024
        ):
            raise ExecutionError("Invalid sandbox export path.")
        scope = execution_scope.get()
        if not scope or (scope.workspace_id, scope.run_id) != (workspace_id, run_id):
            raise ExecutionNotStarted("Run execution scope is unavailable.")
        record, run, _, stale = await self.store.acquire(self.settings, scope, 30)
        try:
            sandbox, reset = await self._connect_record(
                record, scope, 30, profile=run.resource_profile
            )
            if stale:
                await self._stop_stale_processes(sandbox)
            if reset:
                raise ExecutionError("Sandbox export was lost after workspace reset.")
            if not await self.store.current(record, scope):
                raise ExecutionBusy("Run sandbox lease was lost.")

            async def read():
                content = bytearray()
                async with asyncio.timeout(30):
                    stream = await sandbox.files.read_bytes_stream(path)
                    async for chunk in stream:
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            raise ExecutionError("Sandbox export exceeds its limit.")
                return bytes(content)

            return await self._fenced(record, scope, read())
        finally:
            await self.store.release(record)

    async def _close_record(self, record, *, owned=False):
        if not await self.store.closing(record, owned=owned):
            return
        cached = self._sessions.pop(record.id, None)
        if not record.sandbox_id:
            await self.store.closed(record)
            return
        if cached is not None and cached.sandbox.id != record.sandbox_id:
            await cached.sandbox.close()
            cached = None
        try:
            sandbox = (
                cached.sandbox
                if cached
                else await Sandbox.connect(
                    record.sandbox_id,
                    connection_config=self._connection_config(10),
                )
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status == 404:
                await self.capacity.release(record.capacity_token, record.consumer_key)
                await self.store.closed(record)
            return
        self._capacity_slots[sandbox.id] = record.capacity_token
        self._consumer_slots[sandbox.id] = record.consumer_key
        if await self._destroy_sandbox(sandbox):
            await self.store.closed(record)

    async def _destroy_sandbox(self, sandbox) -> bool:
        slot = self._capacity_slots.pop(sandbox.id, None)
        consumer = self._consumer_slots.pop(sandbox.id, None)
        cleanup = asyncio.create_task(sandbox.destroy())
        try:
            await asyncio.wait_for(asyncio.shield(cleanup), 10)
        except asyncio.CancelledError:
            cleanup.add_done_callback(_consume_cleanup)
            raise
        except Exception:
            # The sandbox may live until its native expiry, and its slot with it.
            logger.warning(
                "OpenSandbox cleanup deferred to native TTL",
                extra={"sandbox_id": sandbox.id},
            )
            cleanup.add_done_callback(_consume_cleanup)
            return False
        await self.capacity.release(slot, consumer)
        return True

    async def _require_enforcement(self, sandbox, domains):
        endpoint = await sandbox.get_endpoint(18080)
        url = f"{self.settings.opensandbox_url.rstrip('/')}/v1/sandboxes/{sandbox.id}/proxy/18080/policy"
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=10
        ) as client:
            async with client.stream(
                "GET",
                url,
                headers={
                    **endpoint.headers,
                    "OPEN-SANDBOX-API-KEY": self.settings.opensandbox_api_key,
                },
            ) as response:
                response.raise_for_status()
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > 16384:
                        raise ExecutionError(
                            "OpenSandbox returned an oversized network policy."
                        )
        status = json.loads(payload)
        policy = status.get("policy", {})
        rules = policy.get("egress", [])
        denies = {rule.get("target") for rule in rules if rule.get("action") == "deny"}
        allows = {rule.get("target") for rule in rules if rule.get("action") == "allow"}
        if (
            status.get("enforcementMode") != "dns+nft"
            or policy.get("defaultAction") != "deny"
            or not set(DENIED_NETWORKS).issubset(denies)
            or allows != set(domains)
        ):
            raise ExecutionError(
                "OpenSandbox requires dns+nft enforcement with private-network denial; execution is disabled."
            )


def _consume_cleanup(task):
    if not task.cancelled():
        task.exception()
