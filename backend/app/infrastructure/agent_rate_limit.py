from contextlib import suppress
from dataclasses import dataclass
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infrastructure.config import Settings

_FIXED_WINDOW_SCRIPT = """
local agent_count = redis.call('INCR', KEYS[1])
if agent_count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local consumer_count = redis.call('INCR', KEYS[2])
if consumer_count == 1 then redis.call('EXPIRE', KEYS[2], ARGV[1]) end
return {
  agent_count,
  consumer_count,
  redis.call('TTL', KEYS[1]),
  redis.call('TTL', KEYS[2])
}
"""


@dataclass(frozen=True)
class AgentRateLimitExceeded(Exception):
    retry_after: int


class AgentRateLimitUnavailable(Exception):
    pass


async def enforce_external_agent_rate_limit(
    settings: Settings,
    agent_id: str,
    access_source: str,
    consumer_id: str,
) -> None:
    window_seconds = 60
    window = int(time.time()) // window_seconds
    client = Redis.from_url(
        settings.celery_broker_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        values = await client.eval(
            _FIXED_WINDOW_SCRIPT,
            2,
            f"nexaflow:agent-rate:{agent_id}:{window}",
            f"nexaflow:agent-rate:{agent_id}:{access_source}:{consumer_id}:{window}",
            window_seconds,
        )
    except (RedisError, OSError, TimeoutError) as exc:
        raise AgentRateLimitUnavailable from exc
    finally:
        with suppress(RedisError, OSError, TimeoutError):
            await client.aclose()

    agent_count, consumer_count, agent_ttl, consumer_ttl = map(int, values)
    if (
        agent_count > settings.agent_external_agent_runs_per_minute
        or consumer_count > settings.agent_external_consumer_runs_per_minute
    ):
        raise AgentRateLimitExceeded(max(1, agent_ttl, consumer_ttl))
