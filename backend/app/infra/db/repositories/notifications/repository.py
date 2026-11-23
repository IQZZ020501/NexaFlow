"""SQLAlchemy repository functions for per-user task notifications."""

from datetime import datetime

from sqlalchemy import delete, func, literal, select, union_all, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications.models import UserNotification as UserNotificationOrm
from app.entities.notifications import UserNotification
from app.infra.db import mapping
from app.infra.db.repositories.announcements.repository import (
    visible_message_ordering_query,
)


async def create_notification_idempotent(
    db: AsyncSession,
    entity: UserNotification,
) -> tuple[UserNotification, bool]:
    """Persist a notification once per ``(user_id, dedup_key)`` inside the current txn."""
    try:
        async with db.begin_nested():
            row = await mapping.save(db, UserNotificationOrm, entity)
            await db.flush()
            return (mapping.to_entity(UserNotification, row), True)
    except IntegrityError:
        existing = await db.scalar(
            select(UserNotificationOrm).where(
                UserNotificationOrm.user_id == entity.user_id,
                UserNotificationOrm.dedup_key == entity.dedup_key,
            )
        )
        if existing is not None:
            return (mapping.to_entity(UserNotification, existing), False)
        raise


def _scope_filters(user_id: str, workspace_id: str | None) -> list:
    filters = [UserNotificationOrm.user_id == user_id]
    if workspace_id is not None:
        filters.append(UserNotificationOrm.workspace_id == workspace_id)
    return filters


async def list_user_notifications(
    db: AsyncSession,
    user_id: str,
    workspace_id: str | None,
    *,
    limit: int = 50,
    offset: int = 0,
    message_ids: list[str] | None = None,
) -> tuple[list[UserNotification], int]:
    filters = _scope_filters(user_id, workspace_id)
    if message_ids is not None:
        filters.append(UserNotificationOrm.id.in_(message_ids))
    total = int(
        await db.scalar(select(func.count(UserNotificationOrm.id)).where(*filters)) or 0
    )
    rows = await db.scalars(
        select(UserNotificationOrm)
        .where(*filters)
        .order_by(
            UserNotificationOrm.created_at.desc(),
            UserNotificationOrm.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return ([mapping.to_entity(UserNotification, row) for row in rows.all()], total)


async def count_unread_notifications(
    db: AsyncSession,
    user_id: str,
    workspace_id: str | None,
) -> int:
    filters = [
        *_scope_filters(user_id, workspace_id),
        UserNotificationOrm.read_at.is_(None),
    ]
    return int(
        await db.scalar(select(func.count(UserNotificationOrm.id)).where(*filters)) or 0
    )


async def get_user_notification(
    db: AsyncSession,
    user_id: str,
    notification_id: str,
    workspace_id: str | None,
) -> UserNotification | None:
    filters = [
        *_scope_filters(user_id, workspace_id),
        UserNotificationOrm.id == notification_id,
    ]
    row = await db.scalar(select(UserNotificationOrm).where(*filters))
    return mapping.to_entity(UserNotification, row) if row is not None else None


async def mark_notification_read(
    db: AsyncSession,
    user_id: str,
    notification_id: str,
    workspace_id: str | None,
    read_at: datetime,
) -> bool:
    existing = await get_user_notification(
        db,
        user_id,
        notification_id,
        workspace_id,
    )
    if existing is None:
        return False
    if existing.read_at is None:
        await db.execute(
            update(UserNotificationOrm)
            .where(
                UserNotificationOrm.id == notification_id,
                UserNotificationOrm.user_id == user_id,
                UserNotificationOrm.read_at.is_(None),
            )
            .values(read_at=read_at)
        )
    return True


async def mark_all_notifications_read(
    db: AsyncSession,
    user_id: str,
    workspace_id: str | None,
    read_at: datetime,
) -> int:
    filters = [
        *_scope_filters(user_id, workspace_id),
        UserNotificationOrm.read_at.is_(None),
    ]
    result = await db.execute(
        update(UserNotificationOrm).where(*filters).values(read_at=read_at)
    )
    return int(result.rowcount or 0)


async def delete_notifications_for_user(
    db: AsyncSession,
    user_id: str,
) -> None:
    await db.execute(
        delete(UserNotificationOrm).where(UserNotificationOrm.user_id == user_id)
    )


async def delete_notifications_for_workspace(
    db: AsyncSession,
    workspace_id: str,
) -> None:
    await db.execute(
        delete(UserNotificationOrm).where(
            UserNotificationOrm.workspace_id == workspace_id
        )
    )


async def list_unified_message_keys(
    db: AsyncSession,
    user_id: str,
    workspace_id: str | None,
    now: datetime,
    *,
    limit: int,
    offset: int,
) -> tuple[list[tuple[str, str]], int]:
    """Apply pagination in the database across both inbox sources."""
    notifications = select(
        literal("notification").label("kind"),
        UserNotificationOrm.id.label("id"),
        literal(False).label("pinned"),
        UserNotificationOrm.created_at.label("published_at"),
    ).where(*_scope_filters(user_id, workspace_id))
    inbox = union_all(
        visible_message_ordering_query(workspace_id, now), notifications
    ).subquery()
    total = int(await db.scalar(select(func.count()).select_from(inbox)) or 0)
    rows = await db.execute(
        select(inbox.c.kind, inbox.c.id)
        .order_by(
            inbox.c.pinned.desc(),
            inbox.c.published_at.desc(),
            inbox.c.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return ([(kind, item_id) for kind, item_id in rows], total)
