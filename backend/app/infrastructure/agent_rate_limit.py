import hashlib
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

_redis_client: Redis | None = None


def _rate_limit_redis(url: str) -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _redis_client


class AgentRateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            f"Agent run rate limit exceeded; retry after {retry_after}s."
        )
        self.retry_after = retry_after


class AgentRateLimitUnavailable(Exception):
    pass


class LoginRateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Login rate limit exceeded; retry after {retry_after}s.")
        self.retry_after = retry_after


class LoginRateLimitUnavailable(Exception):
    pass


class PasswordResetRateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            f"Password reset rate limit exceeded; retry after {retry_after}s."
        )
        self.retry_after = retry_after


class PasswordResetRateLimitUnavailable(Exception):
    pass


async def enforce_login_rate_limit(
    settings: Settings,
    username: str,
    source_ip: str | None,
) -> None:
    window_seconds = 60
    window = int(time.time()) // window_seconds
    account_key = hashlib.sha256(username.encode("utf-8")).hexdigest()
    source_key = hashlib.sha256((source_ip or "unknown").encode("utf-8")).hexdigest()
    try:
        values = await _rate_limit_redis(settings.celery_broker_url).eval(
            _FIXED_WINDOW_SCRIPT,
            2,
            f"nexaflow:login-rate:account:{account_key}:{window}",
            f"nexaflow:login-rate:source:{source_key}:{window}",
            window_seconds,
        )
    except (RedisError, OSError, TimeoutError, ValueError) as exc:
        raise LoginRateLimitUnavailable from exc

    account_count, source_count, account_ttl, source_ttl = map(int, values)
    if account_count > 10 or source_count > 300:
        raise LoginRateLimitExceeded(max(1, account_ttl, source_ttl))


async def enforce_password_reset_rate_limit(
    settings: Settings,
    email: str,
    source_ip: str | None,
) -> None:
    window_seconds = 3600
    window = int(time.time()) // window_seconds
    account_key = hashlib.sha256(email.encode("utf-8")).hexdigest()
    source_key = hashlib.sha256((source_ip or "unknown").encode("utf-8")).hexdigest()
    try:
        values = await _rate_limit_redis(settings.celery_broker_url).eval(
            _FIXED_WINDOW_SCRIPT,
            2,
            f"nexaflow:password-reset-rate:account:{account_key}:{window}",
            f"nexaflow:password-reset-rate:source:{source_key}:{window}",
            window_seconds,
        )
    except (RedisError, OSError, TimeoutError, ValueError) as exc:
        raise PasswordResetRateLimitUnavailable from exc

    account_count, source_count, account_ttl, source_ttl = map(int, values)
    if account_count > 3 or source_count > 20:
        raise PasswordResetRateLimitExceeded(max(1, account_ttl, source_ttl))


async def enforce_external_agent_rate_limit(
    settings: Settings,
    agent_id: str,
    access_source: str,
    consumer_id: str,
) -> None:
    window_seconds = 60
    window = int(time.time()) // window_seconds
    try:
        values = await _rate_limit_redis(settings.celery_broker_url).eval(
            _FIXED_WINDOW_SCRIPT,
            2,
            f"nexaflow:agent-rate:{agent_id}:{window}",
            f"nexaflow:agent-rate:{agent_id}:{access_source}:{consumer_id}:{window}",
            window_seconds,
        )
    except (RedisError, OSError, TimeoutError, ValueError) as exc:
        raise AgentRateLimitUnavailable from exc

    agent_count, consumer_count, agent_ttl, consumer_ttl = map(int, values)
    if (
        agent_count > settings.agent_external_agent_runs_per_minute
        or consumer_count > settings.agent_external_consumer_runs_per_minute
    ):
        raise AgentRateLimitExceeded(max(1, agent_ttl, consumer_ttl))
