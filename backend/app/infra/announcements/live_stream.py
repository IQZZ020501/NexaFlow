import asyncio
import json
from contextlib import suppress
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.infra.config.settings import Settings
from app.infra.observability.errors import log_error
from app.infra.observability.logger import get_logger

logger = get_logger("announcement_live_stream")

ANNOUNCEMENT_EVENT_TYPES = frozenset(
    {"announcement.published", "announcement.updated", "announcement.archived"}
)
STREAM_MAXLEN = 2048
STREAM_TTL_SECONDS = 86_400
READ_COUNT = 64
PUBLISH_TIMEOUT_SECONDS = 1.0
READ_BLOCK_MS = 15_000


def announcement_stream_key(scope_type: str, workspace_id: str | None = None) -> str:
    if scope_type == "global":
        return "nexaflow:announcement-live:global"
    if not workspace_id:
        raise ValueError("Workspace announcement streams require a workspace ID.")
    return f"nexaflow:announcement-live:workspace:{workspace_id}"


def _redis_client(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.celery_broker_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=READ_BLOCK_MS / 1000 + 1,
    )


class AnnouncementLiveStreamPublisher:
    def __init__(self, settings: Settings) -> None:
        self._redis = _redis_client(settings)

    async def publish(
        self,
        *,
        scope_type: str,
        workspace_id: str | None,
        event: dict[str, Any],
    ) -> None:
        if event.get("type") not in ANNOUNCEMENT_EVENT_TYPES:
            return
        key = announcement_stream_key(scope_type, workspace_id)
        try:
            payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            async with asyncio.timeout(PUBLISH_TIMEOUT_SECONDS):
                async with self._redis.pipeline(transaction=False) as pipe:
                    pipe.xadd(
                        key,
                        {"payload": payload},
                        maxlen=STREAM_MAXLEN,
                        approximate=True,
                    )
                    pipe.expire(key, STREAM_TTL_SECONDS)
                    await pipe.execute()
        except (RedisError, OSError, TimeoutError) as exc:
            log_error(
                logger,
                "Announcement live event publish unavailable; durable data remains available.",
                exc,
                scope_type=scope_type,
                workspace_id=workspace_id,
            )
        finally:
            await self.close()

    async def close(self) -> None:
        with suppress(Exception):
            await self._redis.aclose()


class AnnouncementLiveStreamReader:
    def __init__(
        self,
        settings: Settings,
        *,
        workspace_id: str | None,
    ) -> None:
        self._redis = _redis_client(settings)
        self._streams = {
            announcement_stream_key("global"): None,
        }
        if workspace_id is not None:
            self._streams[announcement_stream_key("workspace", workspace_id)] = None
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    async def read(
        self,
        *,
        global_after: str | None,
        workspace_after: str | None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        if not self._available:
            return []
        stream_cursors = dict(self._streams)
        global_key = announcement_stream_key("global")
        stream_cursors[global_key] = global_after or "$"
        workspace_key = next(
            (key for key in stream_cursors if ":workspace:" in key),
            None,
        )
        if workspace_key is not None:
            stream_cursors[workspace_key] = workspace_after or "$"
        try:
            streams = await self._redis.xread(
                stream_cursors,
                count=READ_COUNT,
                block=READ_BLOCK_MS,
            )
        except (RedisError, OSError, TimeoutError) as exc:
            self._available = False
            log_error(
                logger,
                "Announcement live event read unavailable; durable messages remain available.",
                exc,
            )
            return []

        entries: list[tuple[str, str, dict[str, Any]]] = []
        for stream_name, stream_entries in streams:
            for entry_id, fields in stream_entries:
                payload = fields.get("payload")
                if not isinstance(payload, str):
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("type") in ANNOUNCEMENT_EVENT_TYPES:
                    entries.append((str(stream_name), str(entry_id), event))
        return entries

    async def close(self) -> None:
        with suppress(Exception):
            await self._redis.aclose()
