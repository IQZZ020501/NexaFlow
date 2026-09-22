"""OpenSandbox lifecycle, bounded I/O and cancellation in one private adapter."""

import asyncio
import base64
import hashlib
import json
import logging
import re
from collections.abc import Hashable
from datetime import timedelta
from pathlib import PurePosixPath
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models import NetworkPolicy, NetworkRule, WriteEntry
from opensandbox.models.execd import ExecutionHandlers, RunCommandOpts
from opensandbox.transport import RetryPolicy

from app.infra.config.settings import Settings
from app.infra.execution.network import DENIED_NETWORKS, validate_egress_domain
from app.ports.execution import ExecutionError, execution_scope

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_METADATA_LABEL_LENGTH = 63
_INVALID_METADATA_LABEL_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


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


class OpenSandboxExecution:
    _sessions: dict[tuple[Hashable, ...], object] = {}
    _session_locks: dict[tuple[Hashable, ...], asyncio.Lock] = {}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(self, request, *, timeout_seconds, max_output_bytes):
        settings = self.settings
        if not settings.opensandbox_api_key or not settings.opensandbox_image:
            raise ExecutionError(
                "OpenSandbox is not configured; local execution is disabled."
            )
        payload = json.dumps(request, ensure_ascii=False, allow_nan=False).encode()
        if len(payload) > MAX_REQUEST_BYTES:
            raise ExecutionError("Execution input exceeds 8 MiB.")
        scope = execution_scope.get()
        domains = self._network_domains(request)
        session_key = self._session_key(request, scope)
        if session_key is None:
            sandbox = await self._create_sandbox(
                scope,
                domains,
                timeout_seconds,
                persistent=False,
            )
            try:
                return await self._run_request(
                    sandbox,
                    request,
                    payload,
                    timeout_seconds,
                    max_output_bytes,
                )
            finally:
                await self._destroy_sandbox(sandbox)

        lock = self._session_locks.setdefault(session_key, asyncio.Lock())
        async with lock:
            sandbox = self._sessions.get(session_key)
            if sandbox is None:
                sandbox = await self._create_sandbox(
                    scope,
                    [],
                    timeout_seconds,
                    persistent=True,
                )
                self._sessions[session_key] = sandbox
            else:
                try:
                    await sandbox.renew(
                        timedelta(
                            seconds=max(60, settings.agent_run_timeout_seconds + 60)
                        )
                    )
                except Exception as exc:
                    self._sessions.pop(session_key, None)
                    await self._destroy_sandbox(sandbox)
                    raise ExecutionError(
                        "OpenSandbox execution is unavailable or failed."
                    ) from exc
            try:
                if domains:
                    await sandbox.patch_egress_rules(
                        [NetworkRule(action="allow", target=domain) for domain in domains]
                    )
                    await self._require_enforcement(sandbox, domains)
                return await self._run_request(
                    sandbox,
                    request,
                    payload,
                    timeout_seconds,
                    max_output_bytes,
                )
            except BaseException:
                self._sessions.pop(session_key, None)
                await self._destroy_sandbox(sandbox)
                raise
            finally:
                if domains and self._sessions.get(session_key) is sandbox:
                    try:
                        await sandbox.delete_egress_rules(domains)
                        await self._require_enforcement(sandbox, [])
                    except BaseException:
                        self._sessions.pop(session_key, None)
                        await self._destroy_sandbox(sandbox)
                        raise

    def _network_domains(self, request) -> list[str]:
        domains = request.get("network_domains", [])
        if not isinstance(domains, list) or any(
            not isinstance(domain, str)
            or domain not in self.settings.opensandbox_egress_domains
            for domain in domains
        ):
            raise ExecutionError("Execution egress exceeds the deployment allowlist.")
        for domain in domains:
            validate_egress_domain(domain)
        return list(dict.fromkeys(domains))

    def _session_key(self, request, scope):
        session_scope = request.get("execution_session")
        if session_scope is None:
            return None
        if session_scope != "agent_run" or scope is None or not scope.run_id:
            raise ExecutionError("Agent Run execution session is unavailable.")
        return (
            self.settings.opensandbox_url,
            self.settings.opensandbox_image,
            scope.workspace_id,
            scope.run_id,
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
    ):
        settings = self.settings
        config = self._connection_config(timeout_seconds)
        sandbox = None
        metadata = {"owner": "nexaflow", "execution": str(uuid4())}
        if scope:
            metadata.update(
                workspace=_metadata_label(scope.workspace_id),
                invocation=_metadata_label(scope.invocation_id),
            )
            if scope.run_id:
                metadata["run"] = _metadata_label(scope.run_id)
        try:
            sandbox = await Sandbox.create(
                settings.opensandbox_image,
                connection_config=config,
                metadata=metadata,
                # Native TTL also reclaims executions after worker death or kill failure.
                timeout=timedelta(
                    seconds=max(
                        60,
                        (
                            settings.agent_run_timeout_seconds + 60
                            if persistent
                            else timeout_seconds + 60
                        ),
                    )
                ),
                ready_timeout=timedelta(seconds=30),
                resource={"cpu": "1", "memory": "512Mi"},
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
            await self._require_enforcement(sandbox, domains)
            return sandbox
        except Exception as exc:
            if sandbox is not None:
                await self._destroy_sandbox(sandbox)
            else:
                await config.close_transport_if_owned()
            raise ExecutionError(
                "OpenSandbox execution is unavailable or failed."
            ) from exc

    async def _run_request(
        self,
        sandbox,
        request,
        payload,
        timeout_seconds,
        max_output_bytes,
    ):
        await sandbox.files.write_files(
            [
                WriteEntry(
                    path="/tmp/nexaflow-request.json",
                    data=payload,
                    mode=400,
                    owner="nexaflow",
                    group="nexaflow",
                )
            ]
        )
        environment = request.get("skill_environment")
        if environment is not None and (
            not isinstance(environment, str)
            or re.fullmatch(r"[a-f0-9]{32}", environment) is None
        ):
            raise ExecutionError("Invalid Skill environment.")
        package_root = (
            f"/tmp/nexaflow-skill/{environment}"
            if environment is not None
            else "/tmp/nexaflow-skill"
        )
        entries = []
        files = request.get("files", {})
        if not isinstance(files, dict):
            raise ExecutionError("Invalid execution package.")
        for name, encoded in files.items():
            if (
                not isinstance(name, str)
                or PurePosixPath(name).is_absolute()
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or "\\" in name
                or ":" in name
            ):
                raise ExecutionError("Invalid execution package path.")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (TypeError, ValueError) as exc:
                raise ExecutionError("Invalid execution package content.") from exc
            entries.append(
                WriteEntry(
                    path=f"{package_root}/{name}",
                    data=data,
                    mode=444,
                    owner="root",
                    group="root",
                )
            )
        if entries:
            await sandbox.files.write_files(entries)
        count = 0

        async def bound_output(message):
            nonlocal count
            count += len(message.text.encode())
            if count > 8192:
                raise ExecutionError("Execution command output exceeds its limit.")

        async with asyncio.timeout(timeout_seconds + 5):
            result = await sandbox.commands.run(
                "/opt/nexaflow/.venv/bin/python -I /opt/nexaflow/job.py /tmp/nexaflow-request.json",
                opts=RunCommandOpts(
                    timeout=timedelta(seconds=timeout_seconds), uid=65532, gid=65532
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
            stream = await sandbox.files.read_bytes_stream(
                "/tmp/nexaflow-response.json"
            )
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
        keys = [
            key
            for key in self._sessions
            if key[:2]
            == (self.settings.opensandbox_url, self.settings.opensandbox_image)
            and key[2:] == (workspace_id, run_id)
        ]
        for key in keys:
            lock = self._session_locks.setdefault(key, asyncio.Lock())
            async with lock:
                sandbox = self._sessions.pop(key, None)
                if sandbox is not None:
                    await self._destroy_sandbox(sandbox)
            self._session_locks.pop(key, None)

    async def _destroy_sandbox(self, sandbox) -> None:
        cleanup = asyncio.create_task(sandbox.destroy())
        try:
            await asyncio.wait_for(asyncio.shield(cleanup), 10)
        except asyncio.CancelledError:
            cleanup.add_done_callback(_consume_cleanup)
            raise
        except Exception:
            logger.warning(
                "OpenSandbox cleanup deferred to native TTL",
                extra={"sandbox_id": sandbox.id},
            )
            cleanup.add_done_callback(_consume_cleanup)

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
