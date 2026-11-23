"""Application services for per-user task notifications and unified message inbox."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.announcements import (
    get_message_summary as get_announcement_message_summary,
)
from app.application.announcements import (
    list_messages as list_announcement_messages,
)
from app.application.announcements import (
    mark_all_messages_read as mark_all_announcement_messages_read,
)
from app.application.announcements import (
    mark_message_read as mark_announcement_message_read,
)
from app.domain.notifications.service import (
    build_notification_copy,
    notification_severity,
)
from app.entities.defaults import utc_now
from app.entities.identity.user import User
from app.entities.notifications import UserNotification
from app.infra.config.settings import Settings
from app.infra.db.repositories.notifications import (
    repository as notification_repository,
)
from app.ports.notifications import build_notification_live_stream_publisher
from app.schemas.notifications import (
    MessageListItemResponse,
    UserTaskNotificationMessageResponse,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def notification_to_message_response(
    entity: UserNotification,
) -> UserTaskNotificationMessageResponse:
    metadata = dict(entity.metadata_json or {})
    target_app_type = _optional_str(metadata.get("target_app_type"))
    if target_app_type not in {"agent", "workflow"}:
        target_app_type = None
    trigger_source = _optional_str(metadata.get("trigger_source"))
    if trigger_source not in {"schedule", "webhook", "manual"}:
        trigger_source = None
    created_at = _as_utc(entity.created_at)
    return UserTaskNotificationMessageResponse(
        id=entity.id,
        kind="notification",
        scope_type="personal",
        workspace_id=entity.workspace_id,
        event_type=entity.event_type,  # type: ignore[arg-type]
        title=entity.title,
        body=entity.body,
        severity=notification_severity(entity.event_type),  # type: ignore[arg-type]
        pinned=False,
        automation_id=entity.automation_id,
        automation_name=_optional_str(metadata.get("automation_name")),
        execution_id=entity.execution_id,
        run_id=entity.run_id,
        target_app_id=_optional_str(metadata.get("target_app_id")),
        target_app_type=target_app_type,  # type: ignore[arg-type]
        trigger_source=trigger_source,  # type: ignore[arg-type]
        metadata=metadata,
        published_at=created_at,
        expires_at=None,
        is_read=entity.read_at is not None,
        read_at=_as_utc(entity.read_at) if entity.read_at is not None else None,
        created_at=created_at,
    )


async def create_task_notification_in_txn(
    db: AsyncSession,
    *,
    user_id: str,
    workspace_id: str,
    automation_id: str | None,
    automation_name: str,
    execution_id: str,
    run_id: str | None,
    event_type: str,
    dedup_key: str,
    target_app_id: str | None = None,
    target_app_type: str | None = None,
    trigger_source: str | None = None,
    error_message: str | None = None,
    result_preview: str | None = None,
) -> tuple[UserNotification, bool]:
    """Create a deduplicated notification inside the caller's open transaction."""
    title, body = build_notification_copy(
        automation_name=automation_name,
        event_type=event_type,
        error_message=error_message,
        result_preview=result_preview,
    )
    metadata: dict[str, Any] = {
        "automation_id": automation_id,
        "automation_name": automation_name,
        "execution_id": execution_id,
        "run_id": run_id,
        "target_app_id": target_app_id,
        "target_app_type": target_app_type,
        "trigger_source": trigger_source,
    }
    entity = UserNotification(
        user_id=user_id,
        workspace_id=workspace_id,
        automation_id=automation_id,
        execution_id=execution_id,
        run_id=run_id,
        event_type=event_type,
        title=title,
        body=body,
        metadata_json=metadata,
        dedup_key=dedup_key,
    )
    return await notification_repository.create_notification_idempotent(db, entity)


async def publish_live_task_notification(
    settings: Settings,
    notification: UserNotification,
) -> None:
    """Publish a newly persisted notification to the recipient's per-user live stream."""
    publisher = build_notification_live_stream_publisher(
        settings,
        user_id=notification.user_id,
    )
    await publisher.publish(
        {
            "type": "notification",
            "id": notification.id,
            "workspace_id": notification.workspace_id,
            "event_type": notification.event_type,
            "automation_id": notification.automation_id,
            "execution_id": notification.execution_id,
            "run_id": notification.run_id,
            "title": notification.title,
        }
    )


async def list_unified_messages(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[MessageListItemResponse], int]:
    keys, total = await notification_repository.list_unified_message_keys(
        db,
        user.id,
        workspace_id,
        utc_now(),
        limit=limit,
        offset=offset,
    )
    announcement_ids = [item_id for kind, item_id in keys if kind == "announcement"]
    notification_ids = [item_id for kind, item_id in keys if kind == "notification"]
    announcements = []
    notifications = []
    if announcement_ids:
        announcements, _ = await list_announcement_messages(
            db,
            user=user,
            workspace_id=workspace_id,
            limit=len(announcement_ids),
            offset=0,
            message_ids=announcement_ids,
        )
    if notification_ids:
        rows, _ = await notification_repository.list_user_notifications(
            db,
            user.id,
            workspace_id,
            limit=len(notification_ids),
            offset=0,
            message_ids=notification_ids,
        )
        notifications = [notification_to_message_response(item) for item in rows]
    by_id = {(item.kind, item.id): item for item in [*announcements, *notifications]}
    return ([by_id[key] for key in keys if key in by_id], total)


async def get_unified_message_summary(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str | None,
) -> tuple[int, datetime | None]:
    announcement_count, next_expiration_at = await get_announcement_message_summary(
        db,
        user=user,
        workspace_id=workspace_id,
    )
    notification_count = await notification_repository.count_unread_notifications(
        db,
        user.id,
        workspace_id,
    )
    return (announcement_count + notification_count, next_expiration_at)


async def mark_unified_message_read(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str | None,
    message_id: str,
) -> None:
    if await notification_repository.mark_notification_read(
        db,
        user.id,
        message_id,
        workspace_id,
        utc_now(),
    ):
        await db.commit()
        return
    await mark_announcement_message_read(
        db,
        user=user,
        workspace_id=workspace_id,
        announcement_id=message_id,
    )


async def mark_all_unified_messages_read(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str | None,
) -> None:
    await mark_all_announcement_messages_read(
        db,
        user=user,
        workspace_id=workspace_id,
    )
    await notification_repository.mark_all_notifications_read(
        db,
        user.id,
        workspace_id,
        utc_now(),
    )
    await db.commit()
