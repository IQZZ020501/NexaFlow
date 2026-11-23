"""Port protocols and factories for per-user live notification streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.infra.config.settings import Settings


@dataclass(frozen=True)
class NotificationLiveEntry:
    entry_id: str
    event: dict[str, object]


class NotificationLiveStreamPublisher(Protocol):
    async def publish(self, event: dict[str, object]) -> None: ...


class NotificationLiveStreamReader(Protocol):
    @property
    def available(self) -> bool: ...

    async def read(
        self,
        *,
        after: str | None = None,
        timeout_ms: int = 15000,
    ) -> list[NotificationLiveEntry]: ...

    async def close(self) -> None: ...


def build_notification_live_stream_publisher(
    settings: Settings,
    *,
    user_id: str,
) -> NotificationLiveStreamPublisher:
    from app.adapters.notifications.live_stream import (
        RedisNotificationLiveStreamPublisher,
    )

    return RedisNotificationLiveStreamPublisher(settings, user_id=user_id)


def build_notification_live_stream_reader(
    settings: Settings,
    *,
    user_id: str,
) -> NotificationLiveStreamReader:
    from app.adapters.notifications.live_stream import RedisNotificationLiveStreamReader

    return RedisNotificationLiveStreamReader(settings, user_id=user_id)
