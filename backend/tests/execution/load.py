"""Exercise saturation and tenant fairness against an explicitly isolated Redis."""

import asyncio
import os
import time
from dataclasses import replace
from uuid import uuid4

import tests.support  # noqa: F401
from tests.support import settings

from app.adapters.execution.capacity import CapacityScope, SandboxCapacity
from app.infra.config.execution_hosts import SandboxHost, host_settings
from app.ports.execution import ExecutionBusy


def scope(label, workspace, number=0, profiles=("standard", "standard")):
    identity = f"{label}-{workspace}-{number:03}"
    return CapacityScope(
        workspace_key=f"{label}-{workspace}",
        reservation={
            "id": identity,
            "profiles": profiles,
            "member": "run",
            "owner": identity,
        },
    )


async def close(capacity, request):
    await capacity.release("tracked", request)
    await capacity.release_reservation(request.reservation["id"], request)


async def check(redis_url):
    label = uuid4().hex
    config = replace(
        settings(),
        celery_broker_url=redis_url,
        opensandbox_url=f"http://load-{label}.example",
        opensandbox_max_sandboxes=8,
        opensandbox_max_sandboxes_per_workspace=8,
        opensandbox_memory_budget_mib=8192,
        opensandbox_cpu_budget=8,
    )
    capacity = SandboxCapacity(config)
    fleet = replace(
        config,
        opensandbox_max_sandboxes_per_workspace=2,
        opensandbox_hosts=tuple(
            SandboxHost(name, f"http://{name}-{label}.example", "fixture", 4)
            for name in ("first", "second")
        ),
    )
    hosts = [SandboxCapacity(host) for host in host_settings(fleet)]
    started = time.monotonic()
    try:
        # A tenant's allowance is shared across hosts, not multiplied by them.
        a, b = scope(label, "quota", 0), scope(label, "quota", 1)
        await hosts[0].acquire(120, a)
        try:
            await hosts[1].acquire(120, b)
        except ExecutionBusy as exc:
            assert exc.reason == "workspace_quota", exc.reason
        else:
            raise AssertionError("Another host bypassed the workspace quota.")
        other = scope(label, "other")
        await hosts[1].acquire(120, other)
        await close(hosts[0], a)
        await hosts[1].acquire(120, b)
        await close(hosts[1], b)
        await close(hosts[1], other)

        seeds = [scope(label, f"seed-{i}") for i in range(4)]
        await asyncio.gather(*(capacity.acquire(120, item) for item in seeds))
        requests = [
            scope(
                label,
                f"workspace-{workspace}",
                number,
                ("small",) if number % 2 else ("standard", "standard"),
            )
            for workspace in range(5)
            for number in range(12)
        ]
        for request in requests:
            try:
                await capacity.acquire(120, request)
            except ExecutionBusy as exc:
                assert exc.reason == "host_capacity", exc.reason
            else:
                raise AssertionError("Saturation admitted another resource bundle.")
        await asyncio.gather(*(close(capacity, item) for item in seeds))

        grants = []
        pending = list(reversed(requests))
        while pending:
            progress = False
            for request in pending[:]:
                try:
                    await capacity.acquire(120, request)
                except ExecutionBusy as exc:
                    assert exc.reason == "fair_queue", exc.reason
                    continue
                async with capacity._redis() as redis:
                    assert await redis.zcard(capacity.key) <= capacity.limit
                grants.append(request)
                pending.remove(request)
                await close(capacity, request)
                progress = True
            assert progress, "Eligible queued work stopped making progress."
        assert len({item.workspace_key for item in grants[:5]}) == 5
        for workspace in range(5):
            observed = [
                item.reservation["id"]
                for item in grants
                if item.workspace_key == f"{label}-workspace-{workspace}"
            ]
            assert observed == sorted(observed), "Workspace FIFO order changed."
        print(
            "EXECUTION_SATURATION_OK "
            f"requests={len(grants)} workspaces=5 "
            f"elapsed_seconds={time.monotonic() - started:.3f}"
        )
    finally:
        for current in [capacity, *hosts]:
            async with current._redis() as redis:
                keys = [key async for key in redis.scan_iter(current.key + "*")]
                keys += [
                    key
                    async for key in redis.scan_iter(
                        f"nexaflow:opensandbox:scopes:*:{label}-*"
                    )
                ]
                if keys:
                    await redis.delete(*keys)


if __name__ == "__main__":
    asyncio.run(check(os.environ["NEXAFLOW_TEST_REDIS_URL"]))
