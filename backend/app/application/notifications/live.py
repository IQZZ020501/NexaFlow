"""Dual-channel SSE stream multiplexing workspace announcements and user notifications."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.entities.identity.user import User
from app.ports.announcements import build_announcement_live_stream_reader
from app.ports.notifications import build_notification_live_stream_reader

if TYPE_CHECKING:
    from app.infra.config.settings import Settings

MESSAGE_STREAM_LIFETIME_SECONDS = 60


@dataclass(frozen=True)
class UnifiedMessageStreamUpdate:
    kind: Literal["announcement", "notification", "keep-alive", "unavailable"]
    event_id: str | None = None
    data: dict[str, object] | None = None


async def stream_unified_message_updates(
    settings: Settings,
    *,
    user: User,
    workspace_id: str | None,
    global_after: str | None,
    workspace_after: str | None,
    notification_after: str | None = None,
    max_lifetime_seconds: float = MESSAGE_STREAM_LIFETIME_SECONDS,
) -> AsyncIterator[UnifiedMessageStreamUpdate]:
    announcement_reader = build_announcement_live_stream_reader(
        settings,
        workspace_id=workspace_id,
    )
    notification_reader = build_notification_live_stream_reader(
        settings,
        user_id=user.id,
    )
    current_global_after = global_after
    current_workspace_after = workspace_after
    current_notification_after = notification_after
    deadline = asyncio.get_running_loop().time() + max_lifetime_seconds
    ann_task: asyncio.Task[list] | None = None
    notif_task: asyncio.Task[list] | None = None
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            if ann_task is None and announcement_reader.available:
                ann_task = asyncio.create_task(
                    announcement_reader.read(
                        global_after=current_global_after,
                        workspace_after=current_workspace_after,
                    )
                )
            if notif_task is None and notification_reader.available:
                notif_task = asyncio.create_task(
                    notification_reader.read(
                        after=current_notification_after,
                    )
                )
            pending = {task for task in (ann_task, notif_task) if task is not None}
            if not pending:
                yield UnifiedMessageStreamUpdate(
                    kind="unavailable",
                    data={"type": "unavailable"},
                )
                return
            done, _ = await asyncio.wait(
                pending,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                return
            emitted = False
            if ann_task is not None and ann_task in done:
                entries = ann_task.result()
                ann_task = None
                for entry in entries:
                    if entry.scope_type == "global":
                        current_global_after = entry.entry_id
                    else:
                        current_workspace_after = entry.entry_id
                    emitted = True
                    yield UnifiedMessageStreamUpdate(
                        kind="announcement",
                        event_id=f"{entry.scope_type}:{entry.entry_id}",
                        data=entry.event,
                    )
            if notif_task is not None and notif_task in done:
                entries = notif_task.result()
                notif_task = None
                for entry in entries:
                    current_notification_after = entry.entry_id
                    emitted = True
                    yield UnifiedMessageStreamUpdate(
                        kind="notification",
                        event_id=f"user:{entry.entry_id}",
                        data=entry.event,
                    )
            if not announcement_reader.available and not notification_reader.available:
                yield UnifiedMessageStreamUpdate(
                    kind="unavailable",
                    data={"type": "unavailable"},
                )
                return
            if not emitted:
                yield UnifiedMessageStreamUpdate(kind="keep-alive")
    finally:
        for task in (ann_task, notif_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (ann_task, notif_task) if task is not None),
            return_exceptions=True,
        )
        await announcement_reader.close()
        await notification_reader.close()
