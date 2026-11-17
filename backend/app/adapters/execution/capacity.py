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
from dataclasses import dataclass, field
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infra.config.settings import Settings
from app.infra.observability.logger import log_event
from app.ports.execution import ExecutionBusy, ExecutionNotStarted

logger = logging.getLogger(__name__)

ACQUIRE_WAIT_SECONDS = 0.0
ACQUIRE_POLL_SECONDS = 0.2

# Each slot is scored by its sandbox's native expiry, so a slot that a crashed
# worker never released frees itself when OpenSandbox reclaims the sandbox.
#
# ARGV: 1 now, 2 host limit (0 = unbounded), 3 expiry, 4 token, 5 lifetime,
#        6 consumer limit, 7 workspace limit, 8 track consumer, 9 track workspace.
_ACQUIRE = """
for i=1,3 do redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', ARGV[1]) end
if tonumber(ARGV[2]) > 0 and redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
  return -1
end
if ARGV[8] == '1' and redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[6]) then
  return -2
end
if ARGV[9] == '1' and redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[7]) then
  return -3
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
    reservation: dict = field(default_factory=dict)

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
        if (
            settings.opensandbox_memory_budget_mib < 0
            or settings.opensandbox_cpu_budget < 0
        ):
            raise ValueError("Sandbox resource budgets must not be negative.")
        self.memory_limit = settings.opensandbox_memory_budget_mib
        self.cpu_limit = settings.opensandbox_cpu_budget
        # Pools have a mix of provisional sizes. Reserve their worst-case cost.
        if self.memory_limit:
            self.memory_limit = max(
                0, self.memory_limit - 2048 * settings.opensandbox_warm_pool_size
            )
            if not self.memory_limit:
                raise ValueError("Sandbox memory budget leaves no on-demand capacity.")
        if self.cpu_limit:
            self.cpu_limit = max(
                0, self.cpu_limit - 2 * settings.opensandbox_warm_pool_size
            )
            if not self.cpu_limit:
                raise ValueError("Sandbox CPU budget leaves no on-demand capacity.")
        endpoint = hashlib.sha256(settings.opensandbox_url.encode()).hexdigest()[:16]
        self.key = f"nexaflow:opensandbox:sandboxes:{endpoint}"
        self.host_id = settings.opensandbox_host_id
        self.scope_prefix = (
            "nexaflow:opensandbox:scopes" if settings.opensandbox_hosts else self.key
        )

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
        return (
            self.limit > 0
            or self.memory_limit > 0
            or self.cpu_limit > 0
            or scope.consumer_key is not None
        )

    async def acquire(
        self,
        lifetime_seconds: float,
        scope: CapacityScope | None = None,
    ) -> str | None:
        """Reserve a slot for one sandbox, waiting briefly when the host is full."""
        scope = scope or CapacityScope()
        if not self._tracking_enabled(scope):
            return None
        if scope.reservation:
            from app.adapters.execution.reservations import acquire_reservation

            return await acquire_reservation(self, lifetime_seconds, scope)
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
                    if acquired > 0:
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
                        raise ExecutionBusy(
                            "OpenSandbox capacity is exhausted.",
                            reason={
                                -1: "host_capacity",
                                -2: "consumer_quota",
                                -3: "workspace_quota",
                            }.get(acquired, "host_capacity"),
                            resources={"guests": 1},
                        )
                    await asyncio.sleep(ACQUIRE_POLL_SECONDS)
        except (RedisError, OSError) as exc:
            raise ExecutionNotStarted(
                "OpenSandbox capacity tracking is unavailable."
            ) from exc

    def _scope_key(self, dimension: str, value: str | None) -> str:
        if not value:
            # An absent scope must not share a bucket with a real one.
            return f"{self.scope_prefix}:{dimension}:none"
        return f"{self.scope_prefix}:{dimension}:{value}"

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
        if scope.reservation:
            from app.adapters.execution.reservations import release_member

            await release_member(self, scope)
            return
        try:
            async with self._redis() as redis:
                released = await redis.zrem(self.key, token)
                for dimension, value in (
                    ("consumer", scope.consumer_key),
                    ("workspace", scope.workspace_key),
                ):
                    if value:
                        await redis.zrem(self._scope_key(dimension, value), token)
            if released:
                from app.infra.execution.wakeup import notify_capacity_released

                await notify_capacity_released(self)
        except (RedisError, OSError):
            logger.warning("OpenSandbox capacity slot release deferred to expiry")

    async def discard_waiter(self, reservation_id):
        if not self.limit and not self.memory_limit and not self.cpu_limit:
            return
        try:
            async with self._redis() as redis:
                await redis.hdel(f"{self.key}:waiting", reservation_id)
        except (RedisError, OSError):
            return

    async def release_reservation(self, reservation_id: str, scope: CapacityScope):
        from app.adapters.execution.reservations import release_reservation

        await release_reservation(self, reservation_id, scope)

    async def restore(self, records):
        from app.adapters.execution.reservations import restore_capacity

        await restore_capacity(self, records)
