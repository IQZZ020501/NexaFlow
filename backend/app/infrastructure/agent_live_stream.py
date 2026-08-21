import asyncio
import json
from contextlib import suppress
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger

logger = get_logger("agent_live_stream")

LIVE_EVENT_TYPES = frozenset({"answer_delta", "answer_reset", "reasoning_delta"})
LIVE_STREAM_MAXLEN = 4096
LIVE_STREAM_TTL_SECONDS = 900
LIVE_STREAM_READ_COUNT = 128
LIVE_STREAM_MAX_BLOCK_MS = 500
LIVE_STREAM_PUBLISH_TIMEOUT_SECONDS = 1.0


def live_stream_key(run_id: str) -> str:
    return f"nexaflow:agent-live:{run_id}"


def _redis_client(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.celery_broker_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


class AgentLiveStreamPublisher:
    def __init__(self, settings: Settings, run_id: str) -> None:
        self._redis = _redis_client(settings)
        self._key = live_stream_key(run_id)
        self._available = True

    async def publish(self, event: dict[str, Any]) -> None:
        if not self._available or event.get("type") not in LIVE_EVENT_TYPES:
            return
        try:
            payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            async with asyncio.timeout(LIVE_STREAM_PUBLISH_TIMEOUT_SECONDS):
                entry_fields = {"payload": payload}
                async with self._redis.pipeline(transaction=False) as pipe:
                    pipe.xadd(
                        self._key,
                        entry_fields,
                        maxlen=LIVE_STREAM_MAXLEN,
                        approximate=True,
                    )
                    pipe.expire(self._key, LIVE_STREAM_TTL_SECONDS)
                    await pipe.execute()
        except (RedisError, OSError, TimeoutError) as exc:
            self._available = False
            log_error(
                logger,
                "Agent live stream publish unavailable; durable execution continues.",
                exc,
            )

    async def close(self) -> None:
        with suppress(Exception):
            await self._redis.aclose()


class AgentLiveStreamReader:
    def __init__(self, settings: Settings, run_id: str) -> None:
        self._redis = _redis_client(settings)
        self._key = live_stream_key(run_id)
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    async def read(
        self,
        after: str | None,
        block_ms: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        if not self._available:
            return []
        cursor = after or "0-0"
        try:
            streams = await self._redis.xread(
                {self._key: cursor},
                count=LIVE_STREAM_READ_COUNT,
                block=max(1, min(block_ms, LIVE_STREAM_MAX_BLOCK_MS)),
            )
        except (RedisError, OSError, TimeoutError) as exc:
            self._available = False
            log_error(
                logger,
                "Agent live stream read unavailable; durable events remain available.",
                exc,
            )
            return []
        entries: list[tuple[str, dict[str, Any]]] = []
        for _stream_name, stream_entries in streams:
            for entry_id, fields in stream_entries:
                payload = fields.get("payload")
                if not isinstance(payload, str):
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("type") in LIVE_EVENT_TYPES:
                    entries.append((str(entry_id), event))
        return entries

    async def close(self) -> None:
        with suppress(Exception):
            await self._redis.aclose()
