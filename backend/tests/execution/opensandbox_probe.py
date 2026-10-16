"""Opt-in phase-zero measurements on an isolated OpenSandbox execution host.

Run from backend with OPENSANDBOX_API_KEY and OPENSANDBOX_PROBE_REDIS_URL set:
    uv run python -m tests.execution.opensandbox_probe --url URL --image IMAGE

Run this on the execution host so Docker can verify the actual sandbox runtime.
Only this invocation's tagged sandboxes and private Redis namespace are cleaned up.
No business configuration or database is loaded. Ordinary Docker measurements need
an explicit --allow-development and never satisfy the Kata prerequisite.
"""

import argparse
import asyncio
import json
import logging
import os
import shlex
import sys
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from opensandbox import AcquirePolicy, PoolCreationSpec, Sandbox, SandboxManager
from opensandbox.async_redis_pool_store import AsyncRedisPoolStateStore
from opensandbox.config import ConnectionConfig
from opensandbox.models import NetworkPolicy, NetworkRule, SandboxFilter, WriteEntry
from opensandbox.models.execd import RunCommandOpts
from opensandbox.pool_async import SandboxPoolAsync
from opensandbox.transport import RetryPolicy
from redis.asyncio import Redis

from app.adapters.execution.opensandbox import OpenSandboxExecution
from app.infra.config.settings import Settings
from app.infra.execution.network import DENIED_NETWORKS

OWNER = "nexaflow-probe"
BRIDGE_TOKEN_HEADER = "X-NexaFlow-MCP-Token"
REQUIRED_CHECKS = (
    "server_version",
    "cold_start",
    "runtime",
    "network_enforcement",
    "connect",
    "renew",
    "metadata_filter",
    "filesystem",
    "background_proxy",
    "warm_pool",
    "cleanup",
)


def prerequisite_complete(report: dict) -> bool:
    checks = report["checks"]
    return (
        report.get("mode") == "kata"
        and report.get("sdk_version") == "0.1.16"
        and report.get("runtime_verified") == "kata-runtime"
        and all(
            checks.get(name, {}).get("status") == "passed" for name in REQUIRED_CHECKS
        )
    )


def failure_details(exc: Exception) -> dict:
    # SDK errors can contain response bodies or credentials. Retain only types
    # and HTTP status codes, never arbitrary exception messages or tracebacks.
    detail = {"error_type": type(exc).__name__}
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        detail["http_status"] = status
    return detail


async def docker_runtime(sandbox_id: str) -> str:
    async def command(*arguments):
        process = await asyncio.create_subprocess_exec(
            "docker",
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), 10)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode:
            raise RuntimeError("Docker runtime verification failed")
        return stdout.decode().strip()

    identifiers = (
        await command(
            "ps",
            "--filter",
            f"label=opensandbox.io/id={sandbox_id}",
            "--format",
            "{{.ID}}",
        )
    ).splitlines()
    if len(identifiers) != 1:
        raise RuntimeError("Run this probe on the sandbox's execution host")
    return await command(
        "inspect", "--format", "{{.HostConfig.Runtime}}", identifiers[0]
    )


class Probe:
    def __init__(self, arguments):
        self.arguments = arguments
        self.probe_id = uuid4().hex
        self.metadata = {"owner": OWNER, "probe": self.probe_id}
        self.ids: set[str] = set()
        self.handles: list = []
        self.manager = None
        self.creation_attempted = False
        self.pools: list = []
        self.redis = None
        self.redis_namespace_used = False
        self.redis_prefix = f"nexaflow:execution-probe:{self.probe_id}"
        self.pool_name = f"probe-{self.probe_id}"
        self.report = {
            "started_at": datetime.now(UTC).isoformat(),
            "probe_id": self.probe_id,
            "sdk_version": version("opensandbox"),
            "mode": "development" if arguments.allow_development else "kata",
            "checks": {},
        }
        # Construct only the settings needed by the existing network verifier.
        # Do not call Settings.from_env(), which loads the business .env.
        self.runtime = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            bootstrap_admin_username="",
            bootstrap_admin_email="",
            bootstrap_admin_name="",
            bootstrap_admin_password="",
            managed_user_initial_password="",
            opensandbox_url=arguments.url,
            opensandbox_api_key=os.environ["OPENSANDBOX_API_KEY"],
            opensandbox_image=arguments.image,
        )
        self.platform = OpenSandboxExecution(self.runtime)

    def config(self):
        endpoint = urlsplit(self.arguments.url)
        return ConnectionConfig(
            domain=endpoint.netloc + endpoint.path.rstrip("/"),
            protocol=endpoint.scheme,
            api_key=self.runtime.opensandbox_api_key,
            use_server_proxy=True,
            request_timeout=timedelta(seconds=90),
            retry_policy=RetryPolicy.disabled(),
            disable_metrics=True,
        )

    def policy(self):
        return NetworkPolicy(
            default_action="deny",
            egress=[
                NetworkRule(action="deny", target=target) for target in DENIED_NETWORKS
            ],
        )

    async def check(self, name, action):
        started = time.monotonic()
        try:
            detail = await action()
        except Exception as exc:
            result = {"status": "failed", **failure_details(exc)}
        else:
            result = {"status": "passed", **(detail or {})}
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        self.report["checks"][name] = result
        print(f"{name}: {result['status']}", file=sys.stderr, flush=True)
        return result["status"] == "passed"

    async def create(self):
        self.creation_attempted = True
        sandbox = await Sandbox.create(
            self.arguments.image,
            connection_config=self.config(),
            metadata=self.metadata,
            timeout=timedelta(seconds=240),
            ready_timeout=timedelta(seconds=60),
            resource={"cpu": "1", "memory": "512Mi"},
            network_policy=self.policy(),
        )
        self.ids.add(sandbox.id)
        self.handles.append(sandbox)
        return sandbox

    async def command(self, sandbox, source, *, uid=65532):
        result = await sandbox.commands.run(
            f"/opt/nexaflow/.venv/bin/python -I -c {shlex.quote(source)}",
            opts=RunCommandOpts(timeout=timedelta(seconds=10), uid=uid, gid=uid),
        )
        if result.error or result.exit_code not in (None, 0):
            raise RuntimeError("Probe command failed")
        return result.text.strip()

    async def server_version(self):
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=10
        ) as client:
            response = await client.get(
                f"{self.arguments.url}/version",
                headers={"OPEN-SANDBOX-API-KEY": self.runtime.opensandbox_api_key},
            )
            response.raise_for_status()
            observed = response.json().get("version")
        if observed != "0.2.3":
            raise RuntimeError("The probe requires server 0.2.3")
        return {"version": observed}

    async def filtered_infos(self, metadata):
        if self.manager is None:
            self.manager = await SandboxManager.create(connection_config=self.config())
        infos = []
        page = 1
        while True:
            result = await self.manager.list_sandbox_infos(
                SandboxFilter(metadata=metadata, page=page, page_size=100)
            )
            # A server ignoring the filter must never cause unrelated deletion.
            if any(
                not all(
                    (info.metadata or {}).get(key) == value
                    for key, value in metadata.items()
                )
                for info in result.sandbox_infos
            ):
                raise RuntimeError("Server did not honor the metadata filter")
            infos.extend(result.sandbox_infos)
            if not result.pagination.has_next_page:
                return infos
            page += 1

    async def runtime_check(self, sandbox):
        observed = await docker_runtime(sandbox.id)
        self.report["runtime_verified"] = observed
        if observed != "kata-runtime" and not self.arguments.allow_development:
            raise RuntimeError("Kata runtime is required")
        return {"docker_runtime": observed}

    async def connect(self, sandbox):
        marker = f"/tmp/nexaflow-probe-{self.probe_id}"
        await self.command(
            sandbox,
            f"from pathlib import Path; Path({marker!r}).write_text('retained')",
        )
        await sandbox.close()
        connected = await Sandbox.connect(
            sandbox.id,
            connection_config=self.config(),
            connect_timeout=timedelta(seconds=30),
        )
        self.handles.append(connected)
        value = await self.command(
            connected, f"from pathlib import Path; print(Path({marker!r}).read_text())"
        )
        if value != "retained":
            raise RuntimeError("Reconnected sandbox lost its files")
        return {"files_retained": True}

    async def renew(self, sandbox):
        renewed = await sandbox.renew(timedelta(seconds=300))
        remaining = (renewed.expires_at - datetime.now(UTC)).total_seconds()
        if not 285 <= remaining <= 305:
            raise RuntimeError("Unexpected renewal deadline")
        return {"remaining_seconds": round(remaining, 3)}

    async def metadata_filter(self, sandbox):
        found = await self.filtered_infos(self.metadata)
        missing = await self.filtered_infos({"owner": OWNER, "probe": uuid4().hex})
        if sandbox.id not in {info.id for info in found} or missing:
            raise RuntimeError("Metadata filtering failed")
        return {"positive_and_negative_filters": True}

    async def filesystem(self, sandbox):
        source = """
import errno, json, os
from pathlib import Path
root = Path('/') / 'nexaflow-probe-root'
try:
    root.mkdir()
except OSError as exc:
    writable, error = False, errno.errorcode.get(exc.errno, 'UNKNOWN')
else:
    root.rmdir()
    writable, error = True, None
workspace = Path('/workspace') if writable else Path('/tmp/nexaflow-probe-workspace')
workspace.mkdir(exist_ok=True)
os.chown(workspace, 65532, 65532)
stat = os.statvfs('/tmp')
mounts = Path('/proc/mounts').read_text().splitlines()
print(json.dumps({'root_writable_as_root': writable, 'root_write_error': error,
    'workspace': str(workspace), 'tmp_total_bytes': stat.f_blocks * stat.f_frsize,
    'tmp_available_bytes': stat.f_bavail * stat.f_frsize,
    'tmp_mount': next((line.split()[:4] for line in mounts if line.split()[1] == '/tmp'), None)}))
"""
        details = json.loads(await self.command(sandbox, source, uid=0))
        path = details["workspace"] + "/nexaflow-probe-user"
        await self.command(
            sandbox,
            f"from pathlib import Path; p = Path({path!r}); p.write_text('uid-65532'); p.unlink()",
        )
        details["workspace_writable_as_uid_65532"] = True
        return details

    async def background_proxy(self, sandbox):
        bearer = uuid4().hex
        seconds = self.arguments.stream_seconds
        source = f"""
import hmac, json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass
    def do_GET(self):
        expected = 'Bearer ' + os.environ['PROBE_BEARER']
        if not hmac.compare_digest(self.headers.get('{BRIDGE_TOKEN_HEADER}', ''), expected):
            self.send_response(401); self.send_header('Content-Length', '0'); self.end_headers(); return
        self.send_response(200)
        if self.path == '/stream':
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close'); self.end_headers()
            for index in range({seconds // 5 + 1}):
                self.wfile.write(('data: %d\\n\\n' % index).encode()); self.wfile.flush()
                if index < {seconds // 5}: time.sleep(5)
            self.close_connection = True
        else:
            data = json.dumps({{'authorization_forwarded': hmac.compare_digest(self.headers.get('Authorization', ''), expected),
                'control_key_forwarded': bool(self.headers.get('OPEN-SANDBOX-API-KEY'))}}).encode()
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
ThreadingHTTPServer(('0.0.0.0', 19081), Handler).serve_forever()
"""
        await sandbox.files.write_files(
            [
                WriteEntry(
                    path="/tmp/nexaflow-probe-http.py",
                    data=source,
                    mode=644,
                    owner="nexaflow",
                    group="nexaflow",
                )
            ]
        )
        result = await sandbox.commands.run(
            "/opt/nexaflow/.venv/bin/python -I /tmp/nexaflow-probe-http.py",
            opts=RunCommandOpts(
                background=True,
                uid=65532,
                gid=65532,
                timeout=timedelta(seconds=seconds + 60),
                envs={"PROBE_BEARER": bearer},
            ),
        )
        if result.error:
            raise RuntimeError("Background process did not start")
        # Close the command owner's transport, as happens when a worker exits.
        await sandbox.close()
        connected = await Sandbox.connect(sandbox.id, connection_config=self.config())
        self.handles.append(connected)
        endpoint = await connected.get_endpoint(19081)
        headers = {
            **endpoint.headers,
            "OPEN-SANDBOX-API-KEY": self.runtime.opensandbox_api_key,
        }
        proxy = f"{self.arguments.url}/v1/sandboxes/{sandbox.id}/proxy/19081"
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=15
        ) as client:
            deadline = time.monotonic() + 20
            while True:
                response = await client.get(
                    proxy + "/health",
                    headers={
                        **headers,
                        BRIDGE_TOKEN_HEADER: "Bearer " + bearer,
                        "Authorization": "Bearer " + bearer,
                    },
                )
                if response.status_code == 200:
                    break
                if time.monotonic() >= deadline:
                    response.raise_for_status()
                    raise RuntimeError("Background server did not become ready")
                await asyncio.sleep(0.2)
            unauthorized = await client.get(proxy + "/health", headers=headers)
            if unauthorized.status_code != 401:
                raise RuntimeError("Proxy did not preserve bridge authentication")
            forwarded = response.json()
            if forwarded.get("control_key_forwarded"):
                raise RuntimeError("Control-plane credential reached the guest")
            started = time.monotonic()
            arrivals = []
            async with (
                asyncio.timeout(seconds + 30),
                client.stream(
                    "GET",
                    proxy + "/stream",
                    headers={**headers, BRIDGE_TOKEN_HEADER: "Bearer " + bearer},
                ) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        if line != f"data: {len(arrivals)}":
                            raise RuntimeError("Stream events were lost or reordered")
                        arrivals.append(time.monotonic() - started)
            if (
                len(arrivals) != seconds // 5 + 1
                or arrivals[0] > 5
                or arrivals[-1] < seconds - 2
            ):
                raise RuntimeError("Proxy buffered or interrupted the stream")
        return {
            "survives_transport_close": True,
            "bearer_required": True,
            "bridge_token_header": BRIDGE_TOKEN_HEADER,
            **forwarded,
            "event_count": len(arrivals),
            "first_event_seconds": round(arrivals[0], 3),
            "stream_seconds": round(arrivals[-1], 3),
        }

    async def warm_pool(self):
        self.creation_attempted = True
        self.redis = Redis.from_url(
            self.arguments.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
        )
        await self.redis.ping()
        self.redis_namespace_used = True
        store = AsyncRedisPoolStateStore(self.redis, key_prefix=self.redis_prefix)
        prepared = set()

        async def prepare(sandbox):
            self.ids.add(sandbox.id)
            self.handles.append(sandbox)
            await self.platform._require_enforcement(sandbox, [])
            prepared.add(sandbox.id)

        for _ in range(2):
            pool = SandboxPoolAsync(
                pool_name=self.pool_name,
                max_idle=1,
                state_store=store,
                connection_config=self.config(),
                creation_spec=PoolCreationSpec(
                    image=self.arguments.image,
                    metadata={**self.metadata, "pool": self.pool_name},
                    network_policy=self.policy(),
                    resource={"cpu": "1", "memory": "512Mi"},
                ),
                warmup_sandbox_preparer=prepare,
                idle_timeout=timedelta(seconds=240),
                primary_lock_ttl=timedelta(seconds=120),
                reconcile_interval=timedelta(seconds=1),
                warmup_ready_timeout=timedelta(seconds=60),
            )
            self.pools.append(pool)
            await pool.start()

        async def wait_for_idle():
            async with asyncio.timeout(90):
                while True:
                    entries = await self.pools[0].snapshot_idle_entries()
                    if len(entries) == 1 and entries[0].sandbox_id in prepared:
                        return entries[0].sandbox_id
                    await asyncio.sleep(0.2)

        first = await wait_for_idle()
        started = time.monotonic()
        acquired = await self.pools[1].acquire(
            sandbox_timeout=timedelta(seconds=180), policy=AcquirePolicy.FAIL_FAST
        )
        self.ids.add(acquired.id)
        self.handles.append(acquired)
        acquire_seconds = time.monotonic() - started
        if acquired.id != first:
            raise RuntimeError("Pool acquisition silently created a cold sandbox")
        await self.platform._require_enforcement(acquired, [])
        info = await acquired.patch_metadata(
            {"run": self.probe_id, "workspace": "probe"}
        )
        if (info.metadata or {}).get("run") != self.probe_id:
            raise RuntimeError("Pool acquisition metadata patch failed")
        if await self.command(acquired, "print('warm')") != "warm":
            raise RuntimeError("Acquired sandbox could not execute")
        replacement = await wait_for_idle()
        if replacement == first:
            raise RuntimeError("Pool did not replenish")
        return {
            "shared_redis_two_clients": True,
            "network_verified_before_idle": True,
            "metadata_patch": True,
            "replenished": True,
            "acquire_seconds": round(acquire_seconds, 3),
        }

    async def cleanup(self):
        failures = []
        # Stop warmup before enumerating owned sandboxes. A shutdown alone does
        # not kill idle entries in SDK 0.1.16, so remove the tagged instances too.
        for pool in self.pools:
            try:
                await pool.resize(0)
                await pool.shutdown(graceful=True)
            except Exception as exc:
                failures.append(failure_details(exc))
        if self.creation_attempted:
            try:
                self.ids.update(
                    info.id for info in await self.filtered_infos(self.metadata)
                )
            except Exception as exc:
                failures.append(failure_details(exc))
        for sandbox_id in sorted(self.ids):
            try:
                await self.manager.kill_sandbox(sandbox_id)
            except Exception as exc:
                # Destroy is idempotent only after an explicit not-found check.
                try:
                    async with httpx.AsyncClient(
                        trust_env=False, follow_redirects=False, timeout=10
                    ) as client:
                        response = await client.get(
                            f"{self.arguments.url}/v1/sandboxes/{sandbox_id}",
                            headers={
                                "OPEN-SANDBOX-API-KEY": self.runtime.opensandbox_api_key
                            },
                        )
                    absent = response.status_code == 404
                except Exception:
                    absent = False
                if not absent:
                    failures.append(failure_details(exc))
        remaining = []
        if self.creation_attempted:
            try:
                remaining = await self.filtered_infos(self.metadata)
            except Exception as exc:
                failures.append(failure_details(exc))
        for sandbox in self.handles:
            try:
                await sandbox.close()
            except Exception as exc:
                failures.append(failure_details(exc))
        if self.redis is not None:
            try:
                keys = (
                    [
                        key
                        async for key in self.redis.scan_iter(
                            match=self.redis_prefix + "*"
                        )
                    ]
                    if self.redis_namespace_used
                    else []
                )
                if keys:
                    await self.redis.delete(*keys)
            except Exception as exc:
                failures.append(failure_details(exc))
            finally:
                await self.redis.aclose()
        if self.manager is not None:
            await self.manager.close()
        if failures or remaining:
            self.report["cleanup_failures"] = failures
            self.report["remaining_sandbox_ids"] = [info.id for info in remaining]
            raise RuntimeError("Probe cleanup incomplete; native TTL is the fallback")
        return {
            "tagged_sandboxes_remaining": 0,
            "redis_namespace_removed": self.redis_namespace_used,
        }

    async def run(self):
        try:
            if not await self.check("server_version", self.server_version):
                return
            samples = []
            for index in range(self.arguments.samples):
                started = time.monotonic()
                sandbox = await self.create()
                ready = time.monotonic()
                if not await self.check("runtime", lambda: self.runtime_check(sandbox)):
                    return
                if not await self.check(
                    "network_enforcement",
                    lambda: self.platform._require_enforcement(sandbox, []),
                ):
                    return
                command_started = time.monotonic()
                if await self.command(sandbox, "print('ready')") != "ready":
                    raise RuntimeError("Cold sandbox could not execute")
                samples.append(
                    {
                        "create_to_ready_seconds": round(ready - started, 3),
                        "first_command_seconds": round(
                            time.monotonic() - command_started, 3
                        ),
                    }
                )
                if index == 0:
                    await self.check("connect", lambda: self.connect(sandbox))
                    # Use a fresh handle after testing transport closure.
                    sandbox = await Sandbox.connect(
                        sandbox.id, connection_config=self.config()
                    )
                    self.handles.append(sandbox)
                    await self.check("renew", lambda: self.renew(sandbox))
                    await self.check(
                        "metadata_filter", lambda: self.metadata_filter(sandbox)
                    )
                    await self.check("filesystem", lambda: self.filesystem(sandbox))
                    await self.check(
                        "background_proxy", lambda: self.background_proxy(sandbox)
                    )
                cleanup_handle = await Sandbox.connect(
                    sandbox.id, connection_config=self.config()
                )
                self.handles.append(cleanup_handle)
                await cleanup_handle.destroy()
            self.report["checks"]["cold_start"] = {
                "status": "passed",
                "resource": {"cpu": "1", "memory": "512Mi"},
                "samples": samples,
            }
            await self.check("warm_pool", self.warm_pool)
        except Exception as exc:
            self.report["checks"]["cold_start"] = {
                "status": "failed",
                **failure_details(exc),
            }
        finally:
            await self.check("cleanup", self.cleanup)
            for name in REQUIRED_CHECKS:
                self.report["checks"].setdefault(
                    name, {"status": "skipped", "reason": "prerequisite_failed"}
                )
            self.report["phase_zero_complete"] = prerequisite_complete(self.report)
            self.report["completed_at"] = datetime.now(UTC).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--redis-url", default=os.environ.get("OPENSANDBOX_PROBE_REDIS_URL")
    )
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--stream-seconds", type=int, default=70)
    parser.add_argument("--allow-development", action="store_true")
    arguments = parser.parse_args()
    endpoint = urlsplit(arguments.url)
    if (
        endpoint.scheme not in ("http", "https")
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        parser.error(
            "--url must be an HTTP(S) origin without credentials, query or fragment"
        )
    arguments.url = arguments.url.rstrip("/")
    if not os.environ.get("OPENSANDBOX_API_KEY"):
        parser.error("Set OPENSANDBOX_API_KEY in the execution-host environment")
    if not arguments.redis_url:
        parser.error("Set OPENSANDBOX_PROBE_REDIS_URL for the SDK shared-pool test")
    if (
        not 1 <= arguments.samples <= 10
        or not 65 <= arguments.stream_seconds <= 120
        or arguments.stream_seconds % 5
    ):
        parser.error(
            "Use 1-10 samples and a stream duration of 65-120 seconds in steps of 5"
        )
    logging.disable(logging.CRITICAL)
    probe = Probe(arguments)
    asyncio.run(probe.run())
    print(json.dumps(probe.report, ensure_ascii=False, indent=2))
    functional = all(
        probe.report["checks"].get(name, {}).get("status") == "passed"
        for name in REQUIRED_CHECKS
    )
    raise SystemExit(
        0
        if functional
        and (arguments.allow_development or probe.report["phase_zero_complete"])
        else 1
    )


if __name__ == "__main__":
    main()
