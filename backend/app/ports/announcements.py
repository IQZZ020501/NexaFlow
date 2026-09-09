"""Announcement live-delivery capability contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from app.infra.config.settings import Settings

AnnouncementStreamScope = Literal["global", "workspace"]


@dataclass(frozen=True)
class AnnouncementStreamEntry:
    scope_type: AnnouncementStreamScope
    entry_id: str
    event: dict[str, Any]


class AnnouncementLiveStreamPublisher(Protocol):
    async def publish(
        self,
        *,
        scope_type: str,
        workspace_id: str | None,
        event: dict[str, object],
    ) -> None: ...

    async def close(self) -> None: ...


class AnnouncementLiveStreamReader(Protocol):
    @property
    def available(self) -> bool: ...

    async def read(
        self,
        *,
        global_after: str | None,
        workspace_after: str | None,
    ) -> list[AnnouncementStreamEntry]: ...

    async def close(self) -> None: ...


def build_announcement_live_stream_publisher(
    settings: Settings,
) -> AnnouncementLiveStreamPublisher:
    from app.adapters.announcements.live_stream import RedisAnnouncementLiveStreamPublisher

    return RedisAnnouncementLiveStreamPublisher(settings)


def build_announcement_live_stream_reader(
    settings: Settings,
    *,
    workspace_id: str | None,
) -> AnnouncementLiveStreamReader:
    from app.adapters.announcements.live_stream import RedisAnnouncementLiveStreamReader

    return RedisAnnouncementLiveStreamReader(settings, workspace_id=workspace_id)


__all__ = [
    "AnnouncementLiveStreamPublisher",
    "AnnouncementLiveStreamReader",
    "AnnouncementStreamEntry",
    "AnnouncementStreamScope",
    "build_announcement_live_stream_publisher",
    "build_announcement_live_stream_reader",
]
