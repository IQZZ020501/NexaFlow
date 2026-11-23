"""Share provider-requested embedding cooldowns across indexing workers."""

import asyncio
import math
from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError

from app.infra.config.settings import Settings
from app.infra.observability.logger import get_logger

logger = get_logger(__name__)

_EXTEND_COOLDOWN = """
local remaining = redis.call('PTTL', KEYS[1])
if remaining < tonumber(ARGV[1]) then
    redis.call('PSETEX', KEYS[1], ARGV[1], '1')
end
"""


@lru_cache(maxsize=4)
def _client(url: str) -> Redis:
    return Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)


def _key(model_id: str) -> str:
    return f"nexaflow:embedding-cooldown:{model_id}"


async def embedding_cooldown_seconds(settings: Settings, model_id: str) -> float:
    if settings.celery_task_always_eager:
        return 0
    try:
        milliseconds = await asyncio.to_thread(
            _client(settings.celery_broker_url).pttl, _key(model_id)
        )
        return max(0, milliseconds) / 1000
    except (RedisError, OSError):
        # The caller still applies its own bounded backoff if sharing is down.
        logger.warning("Unable to read shared embedding cooldown.")
        return 0


async def extend_embedding_cooldown(
    settings: Settings, model_id: str, seconds: float
) -> None:
    if settings.celery_task_always_eager:
        return
    try:
        await asyncio.to_thread(
            _client(settings.celery_broker_url).eval,
            _EXTEND_COOLDOWN,
            1,
            _key(model_id),
            math.ceil(seconds * 1000),
        )
    except (RedisError, OSError):
        logger.warning("Unable to share embedding cooldown; using local backoff.")
