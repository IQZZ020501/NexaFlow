"""Exercise real Redis Lua arbitration against an explicit isolated Redis."""

import asyncio
import os
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import tests.support  # noqa: F401
from tests.support import settings

from app.adapters.execution.capacity import CapacityScope, SandboxCapacity
from app.entities.defaults import utc_now
from app.entities.execution import ExecutionSession
from app.ports.execution import ExecutionBusy


async def check(url):
    config = replace(
        settings(),
        celery_broker_url=url,
        opensandbox_url=f"http://test-{uuid4().hex}",
        opensandbox_max_sandboxes=4,
    )
    capacity = SandboxCapacity(config)

    def scope(
        run, workspace="a", member="run", owner=None, profiles=("standard", "standard")
    ):
        return CapacityScope(
            workspace_key=workspace,
            consumer_key=workspace,
            reservation={
                "id": run,
                "profiles": profiles,
                "member": member,
                "owner": owner or run,
            },
        )

    async def close_bundle(request):
        # Simulate confirmed shutdown of each host in this Run.
        for member in ("run", "mcp"):
            current = replace(
                request, reservation={**request.reservation, "member": member}
            )
            async with capacity._redis() as redis:
                owner = await redis.hget(
                    f"{capacity.key}:reservation:{request.reservation['id']}", member
                )
            if owner:
                current = replace(
                    current, reservation={**current.reservation, "owner": owner}
                )
                await capacity.release("tracked", current)
        await capacity.release_reservation(request.reservation["id"], request)

    async def busy(request, reason=None):
        try:
            await capacity.acquire(60, request)
        except ExecutionBusy as exc:
            if reason:
                assert exc.reason == reason, exc.reason
        else:
            raise AssertionError("Overcommitted sandbox resources")

    try:
        legacy = CapacityScope(workspace_key="legacy", consumer_key="legacy")
        legacy_tokens = [await capacity.acquire(60, legacy) for _ in range(2)]
        await busy(legacy, "consumer_quota")
        for token in legacy_tokens:
            await capacity.release(token, legacy)

        a, b = scope("run-a"), scope("run-b")
        assert await capacity.acquire(60, a) == "run-a:1"
        assert await capacity.acquire(60, a) == "run-a:1"
        await busy(b, "consumer_quota")
        mcp = scope("run-a", member="mcp", owner="host-1")
        assert await capacity.acquire(60, mcp) == "run-a:2"
        await busy(scope("run-a", member="mcp", owner="host-2"), "environment_owned")
        await capacity.release("run-a:2", mcp)
        assert (
            await capacity.acquire(60, scope("run-a", member="mcp", owner="host-2"))
            == "run-a:2"
        )
        await capacity.release("run-a:2", mcp)
        await capacity.release_reservation("run-a", a)
        async with capacity._redis() as redis:
            assert await redis.zcard(capacity.key) == 2
        # A confirmed MCP shutdown keeps its unused promise while code lives.
        async with capacity._redis() as redis:
            assert await redis.zcard(capacity.key) == 2
        # A workspace at quota cannot block a different workspace's queue.
        c = scope("run-c", "c")
        assert await capacity.acquire(60, c) == "run-c:1"
        await close_bundle(a)
        assert await capacity.acquire(60, b) == "run-b:1"
        await close_bundle(b)
        await close_bundle(c)

        # A Redis restart must recover both consumed and promised slots from
        # the committed session before admitting another Run.
        await capacity.restore(
            [
                ExecutionSession(
                    workspace_id="a",
                    run_id="run-a",
                    consumer_key="a",
                    capacity_token="run-a:1",
                    capacity_reservation=a.reservation,
                    creation_pending=True,
                    expires_at=utc_now() + timedelta(seconds=60),
                )
            ]
        )
        capacity.limit = 2
        await busy(scope("after-restart", "other"), "host_capacity")
        async with capacity._redis() as redis:
            assert await redis.zcard(capacity.key) == 2
            assert (
                await redis.hget(f"{capacity.key}:reservation:run-a", "run") == "run-a"
            )
        await close_bundle(a)
        await capacity.release_reservation(
            "after-restart", scope("after-restart", "other")
        )
        capacity.limit = 4

        # Multiple workers racing the same identity reserve exactly one bundle.
        results = await asyncio.gather(*(capacity.acquire(60, a) for _ in range(8)))
        assert len(set(results)) == 1
        async with capacity._redis() as redis:
            assert await redis.zcard(capacity.key) == 2
        await close_bundle(a)

        capacity.memory_limit = 2048
        assert await capacity.acquire(60, scope("heavy", profiles=("heavy",)))
        await busy(scope("small", "other", profiles=("small",)), "memory_budget")
        await close_bundle(scope("heavy", profiles=("heavy",)))
        assert await capacity.acquire(60, scope("small", "other", profiles=("small",)))
        await close_bundle(scope("small", "other", profiles=("small",)))

        capacity.memory_limit = 0
        capacity.cpu_limit = 1
        await busy(scope("cpu", profiles=("heavy",)), "cpu_budget")
        await capacity.release_reservation("cpu", a)
        capacity.cpu_limit = 0
        ephemeral = scope("ephemeral", profiles=("small",))
        ephemeral = replace(
            ephemeral, reservation={**ephemeral.reservation, "ephemeral": True}
        )
        token = await capacity.acquire(60, ephemeral)
        await capacity.release(token, ephemeral)
        async with capacity._redis() as redis:
            assert await redis.zcard(capacity.key) == 0
    finally:
        async with capacity._redis() as redis:
            keys = [key async for key in redis.scan_iter(match=f"{capacity.key}*")]
            if keys:
                await redis.delete(*keys)


if __name__ == "__main__":
    url = os.environ.get("NEXAFLOW_TEST_REDIS_URL")
    if not url:
        raise SystemExit("Set NEXAFLOW_TEST_REDIS_URL to an isolated Redis database.")
    asyncio.run(check(url))
    print("EXECUTION_RESERVATIONS_OK")
