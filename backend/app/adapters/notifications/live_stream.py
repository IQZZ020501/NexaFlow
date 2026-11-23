"""Redis Streams publisher and reader isolated strictly per user."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.ports.notifications import NotificationLiveEntry

if TYPE_CHECKING:
    from app.infra.config.settings import Settings

NOTIFICATION_LIVE_MAXLEN = 500
NOTIFICATION_LIVE_TTL_SECONDS = int(timedelta(days=7).total_seconds())
NOTIFICATION_LIVE_BLOCK_MS = 5000
PUBLISH_TIMEOUT_SECONDS = 1.0
logger = logging.getLogger(__name__)


def user_notification_stream_key(user_id: str) -> str:
    return f"nexaflow:user-notifications:{user_id}"


def _redis_client(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.celery_broker_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=NOTIFICATION_LIVE_BLOCK_MS / 1000 + 1,
    )


def _encode_event(event: dict[str, object]) -> dict[str, str]:
    return {"payload": json.dumps(event, separators=(",", ":"), default=str)}


def _decode_event(fields: dict[object, object]) -> dict[str, object] | None:
    raw_payload = fields.get("payload")
    if raw_payload is None:
        raw_payload = fields.get(b"payload")
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode("utf-8", errors="ignore")
    if not isinstance(raw_payload, str) or not raw_payload:
        return None
    try:
        parsed = json.loads(raw_payload)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


class RedisNotificationLiveStreamPublisher:
    def __init__(self, settings: Settings, *, user_id: str) -> None:
        self._redis = _redis_client(settings)
        self._stream_key = user_notification_stream_key(user_id)

    async def publish(self, event: dict[str, object]) -> None:
        try:
            async with asyncio.timeout(PUBLISH_TIMEOUT_SECONDS):
                async with self._redis.pipeline(transaction=False) as pipe:
                    await pipe.xadd(
                        self._stream_key,
                        _encode_event(event),
                        maxlen=NOTIFICATION_LIVE_MAXLEN,
                        approximate=True,
                    )
                    await pipe.expire(self._stream_key, NOTIFICATION_LIVE_TTL_SECONDS)
                    await pipe.execute()
        except (RedisError, OSError, TimeoutError) as exc:
            logger.warning(
                "User notification live publish skipped (%s): %s",
                self._stream_key,
                type(exc).__name__,
            )
        finally:
            with suppress(Exception):
                await self._redis.aclose()


class RedisNotificationLiveStreamReader:
    def __init__(self, settings: Settings, *, user_id: str) -> None:
        self._redis = _redis_client(settings)
        self._stream_key = user_notification_stream_key(user_id)
        self.available = True

    async def read(
        self,
        *,
        after: str | None = None,
        timeout_ms: int = NOTIFICATION_LIVE_BLOCK_MS,
    ) -> list[NotificationLiveEntry]:
        if not self.available:
            return []
        try:
            response = await self._redis.xread(
                streams={self._stream_key: after or "$"},
                count=50,
                block=max(1, timeout_ms),
            )
        except (RedisError, OSError, TimeoutError) as exc:
            logger.warning(
                "User notification live read failed (%s): %s",
                self._stream_key,
                type(exc).__name__,
            )
            self.available = False
            return []
        if not response:
            return []
        entries: list[NotificationLiveEntry] = []
        for _stream_name, records in response:
            for entry_id, fields in records:
                parsed = _decode_event(fields)
                if parsed is not None:
                    entries.append(
                        NotificationLiveEntry(entry_id=str(entry_id), event=parsed)
                    )
        return entries

    async def close(self) -> None:
        with suppress(Exception):
            await self._redis.aclose()
