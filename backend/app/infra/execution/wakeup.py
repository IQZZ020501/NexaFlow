"""Best-effort release notification; periodic recovery remains authoritative."""

import asyncio
from functools import lru_cache

from celery import Celery


@lru_cache(maxsize=4)
def _publisher(broker_url):
    client = Celery("execution-wakeup", broker=broker_url)
    client.conf.update(
        broker_connection_timeout=1,
        broker_transport_options={"socket_connect_timeout": 1, "socket_timeout": 1},
    )
    return client


async def notify_capacity_released(capacity):
    try:
        async with capacity._redis() as redis:
            if not hasattr(redis, "set") or not await redis.set(
                "nexaflow:opensandbox:wakeup", "1", nx=True, ex=1
            ):
                return
        await asyncio.to_thread(
            _publisher(capacity.broker_url).send_task,
            "app.execution.wake",
            queue="celery",
            retry=False,
        )
    except Exception:
        # A lost notification must neither undo a confirmed deletion nor
        # bypass atomic admission. Beat will recover the original waiter.
        return
