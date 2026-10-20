"""OpenSandbox lifecycle, bounded I/O and cancellation in one private adapter."""

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from collections.abc import Hashable
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
from app.adapters.execution.capacity import CapacityScope, SandboxCapacity
from app.adapters.execution.resources import RESOURCES, request_profile
from app.infra.config.settings import Settings
from app.infra.execution.network import DENIED_NETWORKS, validate_egress_domain
from app.infra.execution.sessions import SessionStore
from app.infra.observability.logger import log_event
from app.ports.execution import (
    ExecutionBridge,
    ExecutionBusy,
    ExecutionError,
    ExecutionNotStarted,
    ExecutionOutcomeUnknown,
    execution_scope,
)

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 8 * 1024 * 1024
# Cold guest creation and cleanup happen inside the caller's budget.
DEADLINE_OVERHEAD_SECONDS = 15.0
CLEANUP_TIMEOUT_SECONDS = 10.0
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


@dataclass
class _RequestProgress:
    dispatched: bool = False
    response: dict | None = None


def _scope_for_execution(scope) -> CapacityScope:
    """Capacity scope for a request that has no durable session yet."""
    workspace_id = getattr(scope, "workspace_id", None)
    return CapacityScope(workspace_key=workspace_id or None)


class OpenSandboxExecution:
    _sessions: dict[str, _Session] = {}
    _session_locks: WeakValueDictionary[tuple[Hashable, ...], asyncio.Lock] = (
        WeakValueDictionary()
    )
    _capacity_slots: dict[str, str] = {}
    _scope_slots: dict[str, CapacityScope] = {}

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
        # Creation, execution and cleanup share one budget. Without it a cold
        # guest plus a failed destroy can occupy the caller for far longer than
        # the requested timeout.
        deadline = time.monotonic() + timeout_seconds + DEADLINE_OVERHEAD_SECONDS
        progress = _RequestProgress()
        try:
            async with asyncio.timeout_at(deadline):
                return await self._execute_request(
                    request, timeout_seconds, max_output_bytes, deadline, progress
                )
        except Exception as exc:
            if progress.response is not None:
                # Session bookkeeping or cleanup cannot undo a confirmed result.
                return progress.response
            if progress.dispatched:
                raise ExecutionOutcomeUnknown(
                    "Execution command may have run, but its result could not be confirmed."
                ) from exc
            if isinstance(exc, TimeoutError):
                raise ExecutionNotStarted("Execution deadline expired before dispatch.") from exc
            raise

    async def _execute_request(self, request, timeout, max_bytes, deadline, progress):
        work_deadline = deadline - min(
            CLEANUP_TIMEOUT_SECONDS, DEADLINE_OVERHEAD_SECONDS
        )
        scope = execution_scope.get()
        sandbox = record = lock = None
        locked = False
        failed = True
        domains = []
        try:
            async with asyncio.timeout_at(work_deadline):
                await self._close_expired_handles()
                domains = self._network_domains(request)
                session_key = self._session_key(request, scope)
                if session_key is None:
                    sandbox = await self._create_sandbox(
                        scope, domains, timeout, persistent=False,
                        profile=request_profile(request), deadline=deadline,
                    )
                    response = await self._run_request(
                        sandbox, request, timeout, max_bytes, progress=progress
                    )
                else:
                    lock = self._session_locks.setdefault(session_key, asyncio.Lock())
                    await lock.acquire()
                    locked = True
                    record, run, reset, stale = await self.store.acquire(
                        self.settings, scope, timeout
                    )

                    async def perform():
                        nonlocal sandbox, reset
                        sandbox, reset = await self._connect_record(
                            record, scope, timeout, reset, run.resource_profile,
                            deadline=deadline,
                        )
                        if stale:
                            await self._stop_stale_processes(sandbox)
                        if not await self.store.current(record, scope):
                            raise ExecutionBusy("Run sandbox lease was lost.")
                        await self._reconcile_egress(sandbox, domains)
                        return await self._execute_record(
                            sandbox, record, request, timeout, max_bytes, progress
                        )

                    response = await self._fenced(record, scope, perform())
                    if reset:
                        response["workspace_reset"] = True
                progress.response = response
                failed = False
                return response
        finally:
            try:
                async with asyncio.timeout_at(deadline):
                    if record is not None:
                        try:
                            if failed and sandbox is not None:
                                # Only the current holder may destroy this guest.
                                await self._close_record(record, owned=True, deadline=deadline)
                            elif sandbox is not None and domains:
                                # Leave time to fence a guest whose policy cannot
                                # be restored before the overall deadline.
                                revoke_deadline = deadline - min(
                                    1.0, DEADLINE_OVERHEAD_SECONDS / 10
                                )
                                try:
                                    async with asyncio.timeout_at(revoke_deadline):
                                        await self._revoke_egress(sandbox, domains)
                                except TimeoutError:
                                    await self._close_record(record, owned=True, deadline=deadline)
                        finally:
                            await self.store.release(record)
                    elif sandbox is not None:
                        await self._destroy_sandbox(sandbox, deadline=deadline)
            except Exception:
                logger.warning("OpenSandbox cleanup deferred to reconciliation or native TTL")
            finally:
                if locked:
                    lock.release()

    async def _execute_record(self, sandbox, record, request, timeout, max_bytes, progress):
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
            sandbox, request, timeout, max_bytes, staged=staged, record=record,
            progress=progress,
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
        self, record, scope, timeout, reset=False, profile="standard", *,
        allow_create=True, deadline=None,
    ):
        if not record.sandbox_id and not allow_create:
            raise ExecutionNotStarted("Run sandbox no longer exists.")
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
                if not allow_create and not await self.store.closing(record, owned=True):
                    raise ExecutionBusy("Run sandbox lease was lost.") from exc
                if sandbox is not None:
                    await sandbox.close()
                self._sessions.pop(record.id, None)
                self._capacity_slots.pop(record.sandbox_id, None)
                self._scope_slots.pop(record.sandbox_id, None)
                await self.capacity.release(record.capacity_token, self._record_scope(record))
                if not allow_create:
                    await self.store.closed(record)
                    raise ExecutionNotStarted("Run sandbox no longer exists.") from exc
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
                capacity_scope=self._record_scope(record),
                session_id=record.id,
                deadline=deadline,
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
                await self._destroy_sandbox(sandbox, deadline=deadline)
                raise
        else:
            await self.capacity.renew(
                record.capacity_token, lifetime, self._record_scope(record)
            )
            if record.capacity_token:
                self._capacity_slots[sandbox.id] = record.capacity_token
                self._scope_slots[sandbox.id] = self._record_scope(record)
        self._sessions[record.id] = _Session(sandbox, record.expires_at)
        return sandbox, reset

    @staticmethod
    def _record_scope(record) -> CapacityScope:
        """Capacity scope of a durable session: its caller and its workspace."""
        return CapacityScope(
            consumer_key=record.consumer_key,
            workspace_key=record.workspace_id or None,
        )

    async def _close_expired_handles(self):
        now = datetime.now(UTC)
        for key, cached in list(self._sessions.items()):
            if _utc_time(cached.expires_at) <= now:
                self._sessions.pop(key, None)
                self._capacity_slots.pop(cached.sandbox.id, None)
                self._scope_slots.pop(cached.sandbox.id, None)
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
        capacity_scope=None,
        session_id=None,
        deadline=None,
    ):
        settings = self.settings
        lifetime = lifetime or self._lifetime_seconds(
            timeout_seconds, persistent=persistent
        )
        capacity_scope = capacity_scope or _scope_for_execution(scope)
        slot = await self.capacity.acquire(lifetime, capacity_scope)
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
                self._scope_slots[sandbox.id] = capacity_scope
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
                self._scope_slots[sandbox.id] = capacity_scope
            log_event(
                logger,
                logging.INFO,
                "OpenSandbox guest created.",
                sandbox_id=sandbox.id,
                profile=profile,
                persistent=persistent,
                domains=len(domains),
            )
            await self._require_enforcement(sandbox, domains)
        except BaseException as exc:
            if sandbox is not None:
                await self._destroy_sandbox(sandbox, deadline=deadline)
            else:
                await config.close_transport_if_owned()
                # A cancelled create may have reached the control plane without
                # returning an ID. Keep its reservation until native expiry.
                if not isinstance(exc, (asyncio.CancelledError, TimeoutError)):
                    await self.capacity.release(slot, capacity_scope)
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

    async def _revoke_egress(self, sandbox, domains) -> None:
        """Remove the egress a command used; never fail the command for it."""
        try:
            await sandbox.delete_egress_rules(list(domains))
        except Exception:
            logger.warning(
                "OpenSandbox egress revocation failed",
                extra={"sandbox_id": sandbox.id, "domains": list(domains)},
            )
        try:
            await self._require_enforcement(sandbox, [])
        except Exception:
            logger.warning(
                "OpenSandbox egress policy verification failed",
                extra={"sandbox_id": sandbox.id},
            )

    def _package_root(self, request) -> str:
        environment = request.get("skill_environment")
        if environment is not None and (
            not isinstance(environment, str)
            or re.fullmatch(r"[a-f0-9]{32}", environment) is None
        ):
            raise ExecutionNotStarted("Invalid Skill environment.")
        return (
            f"/tmp/nexaflow-skill/{environment}"
            if environment is not None
            else "/tmp/nexaflow-skill"
        )

    def _package_files(self, request) -> dict:
        files = request.get("files", {})
        if not isinstance(files, dict):
            raise ExecutionNotStarted("Invalid execution package.")
        for name in files:
            if (
                not isinstance(name, str)
                or PurePosixPath(name).is_absolute()
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or "\\" in name
                or ":" in name
            ):
                raise ExecutionNotStarted("Invalid execution package path.")
        return files

    def _package_key(self, package_root: str, files: dict) -> str:
        """Identity of a package: its root plus a digest of its content.

        Computed from the encoded payload so an already staged package can be
        recognized without decoding it again.
        """
        digest = hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return f"{package_root}:{digest}"

    def _package_entries(self, package_root: str, files: dict) -> list[WriteEntry]:
        entries = []
        for name, encoded in files.items():
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
        return entries

    async def _run_request(
        self,
        sandbox,
        request,
        timeout_seconds,
        max_output_bytes,
        *,
        staged: set[str] | None = None,
        record=None,
        progress,
    ):
        package_root = self._package_root(request)
        files = self._package_files(request)
        package_key = self._package_key(package_root, files)
        entries = []
        package_pending = False
        if staged is None or package_key not in staged:
            # Decode only what still has to be written. A reused session
            # already holds these bytes in the guest.
            entries = self._package_entries(package_root, files)
            package_pending = bool(entries)
        mounted = request.get("skill_mounts", {})
        if not isinstance(mounted, dict):
            raise ExecutionNotStarted("Invalid Skill mounts.")
        for name, mount_files in mounted.items():
            if not isinstance(name, str) or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,63}", name
            ):
                raise ExecutionNotStarted("Invalid Skill mount name.")
            mount_files = self._package_files({"files": mount_files})
            mount_root = self._package_root({})
            mount_key = f"/skills/{name}:{self._package_key(mount_root, mount_files)}"
            if staged is not None and mount_key in staged:
                continue
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
                for entry in self._package_entries(mount_root, mount_files)
            )
            if staged is not None:
                staged.add(mount_key)
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
            # From dispatch onward, losing the reply cannot prove nothing ran.
            progress.dispatched = True
            scope = execution_scope.get()
            if scope is not None:
                scope.attempt.unconfirmed = True
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
            if scope is not None:
                scope.attempt.unconfirmed = False
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
        # A read never creates a guest: a missing session means the workspace
        # is gone, and a fresh guest would only hold an empty workspace.
        record, run, _, stale = await self.store.acquire_existing(
            self.settings, scope, 30
        )
        try:
            sandbox, reset = await self._connect_record(
                record, scope, 30, profile=run.resource_profile, allow_create=False
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

    async def _close_record(self, record, *, owned=False, deadline=None):
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
                await self.capacity.release(
                    record.capacity_token, self._record_scope(record)
                )
                await self.store.closed(record)
            return
        self._capacity_slots[sandbox.id] = record.capacity_token
        self._scope_slots[sandbox.id] = self._record_scope(record)
        if await self._destroy_sandbox(sandbox, deadline=deadline):
            await self.store.closed(record)

    async def _destroy_sandbox(self, sandbox, *, deadline=None) -> bool:
        slot = self._capacity_slots.get(sandbox.id)
        scope = self._scope_slots.get(sandbox.id)
        cleanup = asyncio.create_task(sandbox.destroy())
        try:
            remaining = CLEANUP_TIMEOUT_SECONDS
            if deadline is not None:
                remaining = min(remaining, max(0, deadline - time.monotonic()))
            await asyncio.wait_for(asyncio.shield(cleanup), remaining)
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
        await self.capacity.release(slot, scope)
        self._capacity_slots.pop(sandbox.id, None)
        self._scope_slots.pop(sandbox.id, None)
        return True

    async def _read_policy(self, sandbox) -> tuple[dict, dict, set, set]:
        """Read the effective egress policy of a guest.

        Returns the raw status, the policy, the denied targets and the
        currently allowed targets.
        """
        return await self._fetch_policy(sandbox)

    async def _fetch_policy(self, sandbox) -> tuple[dict, dict, set, set]:
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
        return status, policy, denies, allows

    def _assert_enforcement(self, status, policy, denies) -> None:
        """Enforce the security invariants that no rule change can relax."""
        if (
            status.get("enforcementMode") != "dns+nft"
            or policy.get("defaultAction") != "deny"
            or not set(DENIED_NETWORKS).issubset(denies)
        ):
            raise ExecutionError(
                "OpenSandbox requires dns+nft enforcement with private-network denial; execution is disabled."
            )

    async def _require_enforcement(self, sandbox, domains):
        status, policy, denies, allows = await self._read_policy(sandbox)
        self._assert_enforcement(status, policy, denies)
        if allows != set(domains):
            raise ExecutionError(
                "OpenSandbox network policy does not match the requested egress; execution is disabled."
            )

    async def _reconcile_egress(self, sandbox, domains) -> None:
        """Make the guest's allow list exactly the requested domains.

        A worker that died between granting and revoking an egress rule leaves
        the guest with a wider allow list than the current request. Reconciling
        instead of demanding an exact match keeps the workspace: the leftover
        rule is removed before any new code runs.
        """
        try:
            status, policy, denies, allows = await self._read_policy(sandbox)
            self._assert_enforcement(status, policy, denies)
            desired = set(domains)
            stale = sorted(allows - desired)
            missing = sorted(desired - allows)
            if stale:
                await sandbox.delete_egress_rules(stale)
            if missing:
                await sandbox.patch_egress_rules(
                    [NetworkRule(action="allow", target=domain) for domain in missing]
                )
            await self._require_enforcement(sandbox, domains)
        except ExecutionError as exc:
            raise ExecutionNotStarted(str(exc)) from exc
        except Exception as exc:
            raise ExecutionNotStarted(_UNAVAILABLE) from exc


def _consume_cleanup(task):
    if not task.cancelled():
        task.exception()
