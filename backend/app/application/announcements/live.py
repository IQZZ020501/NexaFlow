from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.workspaces.service import build_workspace_context
from app.entities.identity.user import User
from app.ports.announcements import build_announcement_live_stream_reader

if TYPE_CHECKING:
    from app.infra.config.settings import Settings


@dataclass(frozen=True)
class MessageStreamUpdate:
    kind: Literal["announcement", "keep-alive", "unavailable"]
    event_id: str | None = None
    data: dict[str, object] | None = None


async def validate_message_workspace_access(
    db: AsyncSession,
    user: User,
    workspace_id: str | None,
) -> None:
    if workspace_id is not None:
        await build_workspace_context(db, user, workspace_id)


async def stream_message_updates(
    settings: Settings,
    *,
    workspace_id: str | None,
    global_after: str | None,
    workspace_after: str | None,
) -> AsyncIterator[MessageStreamUpdate]:
    reader = build_announcement_live_stream_reader(
        settings,
        workspace_id=workspace_id,
    )
    current_global_after = global_after
    current_workspace_after = workspace_after
    try:
        while True:
            entries = await reader.read(
                global_after=current_global_after,
                workspace_after=current_workspace_after,
            )
            if not reader.available:
                yield MessageStreamUpdate(
                    kind="unavailable",
                    data={"type": "unavailable"},
                )
                return
            if not entries:
                yield MessageStreamUpdate(kind="keep-alive")
                continue
            for entry in entries:
                if entry.scope_type == "global":
                    current_global_after = entry.entry_id
                else:
                    current_workspace_after = entry.entry_id
                yield MessageStreamUpdate(
                    kind="announcement",
                    event_id=f"{entry.scope_type}:{entry.entry_id}",
                    data=entry.event,
                )
    finally:
        await reader.close()
