"""Deployment-wide bound on live OpenSandbox executions, tracked in Redis.

Capacity accounting is opt-in: a deployment without a host limit keeps the
previous behaviour of unbounded creation and no Redis dependency. Once a host
limit exists, every live guest is booked in Redis and the per-scope limits
apply as well.
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infra.config.settings import Settings
from app.infra.observability.logger import log_event
from app.ports.execution import ExecutionBusy, ExecutionNotStarted

logger = logging.getLogger(__name__)

ACQUIRE_WAIT_SECONDS = 5.0
ACQUIRE_POLL_SECONDS = 0.2

# Each slot is scored by its sandbox's native expiry, so a slot that a crashed
# worker never released frees itself when OpenSandbox reclaims the sandbox.
#
# ARGV: 1 now, 2 host limit (0 = unbounded), 3 expiry, 4 token, 5 lifetime,
#        6 consumer limit, 7 workspace limit, 8 track consumer, 9 track workspace.
_ACQUIRE = """
for i=1,3 do redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', ARGV[1]) end
if tonumber(ARGV[2]) > 0 and redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
  return 0
end
if ARGV[8] == '1' and redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[6]) then
  return 0
end
if ARGV[9] == '1' and redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[7]) then
  return 0
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
if redis.call('PTTL', KEYS[1]) < tonumber(ARGV[5]) then
  redis.call('PEXPIRE', KEYS[1], ARGV[5])
end
if ARGV[8] == '1' then
  redis.call('ZADD', KEYS[2], ARGV[3], ARGV[4])
  if redis.call('PTTL', KEYS[2]) < tonumber(ARGV[5]) then
    redis.call('PEXPIRE', KEYS[2], ARGV[5])
  end
end
if ARGV[9] == '1' then
  redis.call('ZADD', KEYS[3], ARGV[3], ARGV[4])
  if redis.call('PTTL', KEYS[3]) < tonumber(ARGV[5]) then
    redis.call('PEXPIRE', KEYS[3], ARGV[5])
  end
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


@dataclass(frozen=True)
class CapacityScope:
    """Who a live sandbox belongs to, for per-scope capacity bounds.

    ``consumer_key`` is the external caller of a public or API Run.
    ``workspace_key`` is the workspace that owns the Run; it applies to every
    Run so one tenant cannot occupy the whole deployment.
    """

    consumer_key: str | None = None
    workspace_key: str | None = None

    @property
    def tracked(self) -> bool:
        return bool(self.consumer_key or self.workspace_key)


class SandboxCapacity:
    def __init__(self, settings: Settings) -> None:
        self.limit = (
            settings.opensandbox_max_sandboxes - settings.opensandbox_warm_pool_size
            if settings.opensandbox_max_sandboxes
            else 0
        )
        self.consumer_limit = settings.opensandbox_max_sandboxes_per_consumer
        self.workspace_limit = settings.opensandbox_max_sandboxes_per_workspace
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

    def _tracking_enabled(self, scope: CapacityScope) -> bool:
        """A host limit turns capacity accounting on for the deployment.

        Without a host limit the deployment is explicitly unbounded, so it
        keeps working without Redis; only a public/API caller, which always
        has a per-consumer bound, still needs accounting.
        """
        return self.limit > 0 or scope.consumer_key is not None

    async def acquire(
        self,
        lifetime_seconds: float,
        scope: CapacityScope | None = None,
    ) -> str | None:
        """Reserve a slot for one sandbox, waiting briefly when the host is full."""
        scope = scope or CapacityScope()
        if not self._tracking_enabled(scope):
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
                        self.consumer_limit,
                        self.workspace_limit,
                        "1" if scope.consumer_key else "0",
                        "1" if scope.workspace_key else "0",
                    )
                    acquired = await redis.eval(
                        _ACQUIRE,
                        3,
                        self.key,
                        self._scope_key("consumer", scope.consumer_key),
                        self._scope_key("workspace", scope.workspace_key),
                        *arguments,
                    )
                    if acquired:
                        return token
                    if time.monotonic() >= deadline:
                        log_event(
                            logger,
                            logging.WARNING,
                            "OpenSandbox capacity exhausted.",
                            host_limit=self.limit,
                            consumer_limit=self.consumer_limit,
                            workspace_limit=self.workspace_limit,
                            consumer_key=scope.consumer_key or "-",
                            workspace_key=scope.workspace_key or "-",
                        )
                        raise ExecutionBusy("OpenSandbox capacity is exhausted.")
                    await asyncio.sleep(ACQUIRE_POLL_SECONDS)
        except (RedisError, OSError) as exc:
            raise ExecutionNotStarted(
                "OpenSandbox capacity tracking is unavailable."
            ) from exc

    def _scope_key(self, dimension: str, value: str | None) -> str:
        if not value:
            # An absent scope must not share a bucket with a real one.
            return f"{self.key}:{dimension}:none"
        return f"{self.key}:{dimension}:{value}"

    async def renew(
        self,
        token: str | None,
        lifetime_seconds: float,
        scope: CapacityScope | None = None,
    ) -> None:
        if token is None:
            return
        scope = scope or CapacityScope()
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
                for dimension, value in (
                    ("consumer", scope.consumer_key),
                    ("workspace", scope.workspace_key),
                ):
                    if value:
                        await redis.eval(
                            _RENEW,
                            1,
                            self._scope_key(dimension, value),
                            round(time.time() * 1000) + lifetime_ms,
                            token,
                            lifetime_ms,
                        )
        except (RedisError, OSError):
            logger.warning("OpenSandbox capacity slot renewal deferred to expiry")

    async def release(
        self, token: str | None, scope: CapacityScope | None = None
    ) -> None:
        if token is None:
            return
        scope = scope or CapacityScope()
        try:
            async with self._redis() as redis:
                await redis.zrem(self.key, token)
                for dimension, value in (
                    ("consumer", scope.consumer_key),
                    ("workspace", scope.workspace_key),
                ):
                    if value:
                        await redis.zrem(self._scope_key(dimension, value), token)
        except (RedisError, OSError):
            logger.warning("OpenSandbox capacity slot release deferred to expiry")
