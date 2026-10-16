"""SDK-owned prewarming with a deployment-wide Redis leader and idle store."""

import asyncio
import hashlib
from datetime import timedelta

from opensandbox import AcquirePolicy, PoolCreationSpec
from opensandbox.async_redis_pool_store import AsyncRedisPoolStateStore
from opensandbox.models import NetworkPolicy, NetworkRule
from opensandbox.pool_async import SandboxPoolAsync
from redis.asyncio import Redis

from app.adapters.execution.resources import RESOURCES, warm_quotas
from app.infra.execution.network import DENIED_NETWORKS

_pools = {}
_locks = {}


def pool_name(settings, profile):
    digest = hashlib.sha256(
        f"{settings.opensandbox_url}|{settings.opensandbox_image}|{RESOURCES[profile]}".encode()
    ).hexdigest()[:24]
    return f"nexaflow-{profile}-{digest}"


def current_pool_names(settings):
    return {
        pool_name(settings, profile)
        for profile, size in warm_quotas(settings.opensandbox_warm_pool_size).items()
        if size
    }


async def acquire(platform, profile, lifetime):
    size = warm_quotas(platform.settings.opensandbox_warm_pool_size)[profile]
    if not size:
        return None
    name = pool_name(platform.settings, profile)
    key = (asyncio.get_running_loop(), name)
    async with _locks.setdefault(key, asyncio.Lock()):
        pool = _pools.get(key)
        if pool is None:
            redis = Redis.from_url(
                platform.settings.celery_broker_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5,
            )
            pool = SandboxPoolAsync(
                pool_name=name,
                max_idle=size,
                state_store=AsyncRedisPoolStateStore(
                    redis, key_prefix="nexaflow:execution:pools"
                ),
                connection_config=platform._connection_config(60),
                creation_spec=PoolCreationSpec(
                    image=platform.settings.opensandbox_image,
                    resource=RESOURCES[profile],
                    metadata={"owner": "nexaflow", "pool": name},
                    network_policy=NetworkPolicy(
                        default_action="deny",
                        egress=[
                            NetworkRule(action="deny", target=cidr)
                            for cidr in DENIED_NETWORKS
                        ],
                    ),
                ),
                warmup_sandbox_preparer=lambda sandbox: platform._require_enforcement(
                    sandbox, []
                ),
                idle_timeout=timedelta(seconds=240),
                primary_lock_ttl=timedelta(seconds=120),
                warmup_ready_timeout=timedelta(seconds=60),
                reconcile_interval=timedelta(seconds=5),
            )
            await pool.start()
            _pools[key] = pool
    return await pool.acquire(
        sandbox_timeout=timedelta(seconds=lifetime), policy=AcquirePolicy.DIRECT_CREATE
    )
