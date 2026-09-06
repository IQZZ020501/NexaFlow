import hashlib
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infrastructure.config import Settings

_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {count, redis.call('TTL', KEYS[1])}
"""
_client: Redis | None = None


class EnterpriseLoginRateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Enterprise login rate limit exceeded.")
        self.retry_after = retry_after


class EnterpriseLoginRateLimitUnavailable(Exception):
    pass


async def enforce_enterprise_login_rate_limit(
    settings: Settings, source_ip: str | None
) -> None:
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.celery_broker_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    window_seconds = 60
    window = int(time.time()) // window_seconds
    source = hashlib.sha256((source_ip or "unknown").encode()).hexdigest()
    try:
        count, retry_after = map(
            int,
            await _client.eval(
                _SCRIPT,
                1,
                f"nexaflow:enterprise-login-rate:{source}:{window}",
                window_seconds,
            ),
        )
    except (RedisError, OSError, TimeoutError, ValueError) as exc:
        raise EnterpriseLoginRateLimitUnavailable from exc
    if count > 60:
        raise EnterpriseLoginRateLimitExceeded(max(1, retry_after))
