"""Deployment-wide bound on live OpenSandbox executions, tracked in Redis."""

import asyncio
import hashlib
import logging
import time
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infra.config.settings import Settings
from app.ports.execution import ExecutionBusy, ExecutionNotStarted

logger = logging.getLogger(__name__)

ACQUIRE_WAIT_SECONDS = 5.0
ACQUIRE_POLL_SECONDS = 0.2

# Each slot is scored by its sandbox's native expiry, so a slot that a crashed
# worker never released frees itself when OpenSandbox reclaims the sandbox.
_ACQUIRE = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
if redis.call('PTTL', KEYS[1]) < tonumber(ARGV[5]) then
  redis.call('PEXPIRE', KEYS[1], ARGV[5])
end
return 1
"""
_RENEW = """
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[2])
if redis.call('PTTL', KEYS[1]) < tonumber(ARGV[3]) then
  redis.call('PEXPIRE', KEYS[1], ARGV[3])
end
return 1
"""
_ACQUIRE_CONSUMER = """
for i=1,2 do redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', ARGV[1]) end
if (tonumber(ARGV[2]) > 0 and redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]))
  or redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[6]) then return 0 end
for i=1,2 do
  redis.call('ZADD', KEYS[i], ARGV[3], ARGV[4])
  if redis.call('PTTL', KEYS[i]) < tonumber(ARGV[5]) then redis.call('PEXPIRE', KEYS[i], ARGV[5]) end
end
return 1
"""


class SandboxCapacity:
    def __init__(self, settings: Settings) -> None:
        self.limit = (
            settings.opensandbox_max_sandboxes - settings.opensandbox_warm_pool_size
            if settings.opensandbox_max_sandboxes
            else 0
        )
        self.consumer_limit = settings.opensandbox_max_sandboxes_per_consumer
        self.broker_url = settings.celery_broker_url
        endpoint = hashlib.sha256(settings.opensandbox_url.encode()).hexdigest()[:16]
        self.key = f"nexaflow:opensandbox:sandboxes:{endpoint}"

    def _redis(self) -> Redis:
        return Redis.from_url(
            self.broker_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )

    async def acquire(
        self, lifetime_seconds: float, consumer_key: str | None = None
    ) -> str | None:
        """Reserve a slot for one sandbox, waiting briefly when the host is full."""
        if self.limit <= 0 and consumer_key is None:
            return None
        token = uuid4().hex
        lifetime_ms = round(lifetime_seconds * 1000)
        deadline = time.monotonic() + ACQUIRE_WAIT_SECONDS
        try:
            async with self._redis() as redis:
                while True:
                    now_ms = round(time.time() * 1000)
                    arguments = (
                        now_ms,
                        self.limit,
                        now_ms + lifetime_ms,
                        token,
                        lifetime_ms,
                    )
                    acquired = (
                        await redis.eval(
                            _ACQUIRE_CONSUMER,
                            2,
                            self.key,
                            self._consumer_key(consumer_key),
                            *arguments,
                            self.consumer_limit,
                        )
                        if consumer_key
                        else await redis.eval(_ACQUIRE, 1, self.key, *arguments)
                    )
                    if acquired:
                        return token
                    if time.monotonic() >= deadline:
                        raise ExecutionBusy("OpenSandbox capacity is exhausted.")
                    await asyncio.sleep(ACQUIRE_POLL_SECONDS)
        except (RedisError, OSError) as exc:
            raise ExecutionNotStarted(
                "OpenSandbox capacity tracking is unavailable."
            ) from exc

    def _consumer_key(self, consumer_key):
        return f"{self.key}:consumer:{consumer_key}"

    async def renew(
        self,
        token: str | None,
        lifetime_seconds: float,
        consumer_key: str | None = None,
    ) -> None:
        if token is None:
            return
        lifetime_ms = round(lifetime_seconds * 1000)
        try:
            async with self._redis() as redis:
                await redis.eval(
                    _RENEW,
                    1,
                    self.key,
                    round(time.time() * 1000) + lifetime_ms,
                    token,
                    lifetime_ms,
                )
                if consumer_key:
                    await redis.eval(
                        _RENEW,
                        1,
                        self._consumer_key(consumer_key),
                        round(time.time() * 1000) + lifetime_ms,
                        token,
                        lifetime_ms,
                    )
        except (RedisError, OSError):
            logger.warning("OpenSandbox capacity slot renewal deferred to expiry")

    async def release(self, token: str | None, consumer_key: str | None = None) -> None:
        if token is None:
            return
        try:
            async with self._redis() as redis:
                await redis.zrem(self.key, token)
                if consumer_key:
                    await redis.zrem(self._consumer_key(consumer_key), token)
        except (RedisError, OSError):
            logger.warning("OpenSandbox capacity slot release deferred to expiry")
