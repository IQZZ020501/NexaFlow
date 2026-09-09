from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit.services import record_audit_log
from app.entities.announcements.models import Announcement, AnnouncementRead
from app.entities.defaults import utc_now
from app.entities.identity.user import User
from app.infra.announcements.live_stream import AnnouncementLiveStreamPublisher
from app.infra.config.settings import Settings
from app.infra.db.repositories.announcements import repository
from app.schemas.announcements.contracts import (
    AnnouncementCreateRequest,
    AnnouncementMessageResponse,
    AnnouncementResponse,
    AnnouncementUpdateRequest,
)

AnnouncementScope = Literal["global", "workspace"]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _announcement_response(item: Announcement) -> AnnouncementResponse:
    return AnnouncementResponse(
        id=item.id,
        scope_type=item.scope_type,
        workspace_id=item.workspace_id,
        title=item.title,
        body=item.body,
        severity=item.severity,
        pinned=item.pinned,
        status=item.status,
        published_at=item.published_at,
        expires_at=item.expires_at,
        created_by_user_id=item.created_by_user_id,
        updated_by_user_id=item.updated_by_user_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _message_response(
    item: Announcement,
    read: AnnouncementRead | None,
) -> AnnouncementMessageResponse:
    assert item.published_at is not None
    return AnnouncementMessageResponse(
        id=item.id,
        scope_type=item.scope_type,
        workspace_id=item.workspace_id,
        title=item.title,
        body=item.body,
        severity=item.severity,
        pinned=item.pinned,
        published_at=item.published_at,
        expires_at=item.expires_at,
        is_read=read is not None,
        read_at=read.read_at if read is not None else None,
        created_at=item.created_at,
    )


def _event(item: Announcement, event_type: str) -> dict[str, object]:
    return {
        "type": event_type,
        "message_id": item.id,
        "scope_type": item.scope_type,
        "workspace_id": item.workspace_id,
    }


async def _publish_live_event(
    settings: Settings,
    item: Announcement,
    event_type: str,
) -> None:
    publisher = AnnouncementLiveStreamPublisher(settings)
    try:
        await publisher.publish(
            scope_type=item.scope_type,
            workspace_id=item.workspace_id,
            event=_event(item, event_type),
        )
    finally:
        await publisher.close()


def _validate_expiry(
    expires_at: datetime | None,
    published_at: datetime | None,
) -> datetime | None:
    expires_at = _as_utc(expires_at)
    published_at = _as_utc(published_at)
    if expires_at is not None and published_at is not None and expires_at <= published_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Announcement expiry must be after publication.",
        )
    return expires_at


async def create_announcement(
    db: AsyncSession,
    *,
    scope_type: AnnouncementScope,
    workspace_id: str | None,
    actor: User,
    payload: AnnouncementCreateRequest,
) -> AnnouncementResponse:
    if scope_type == "global" and workspace_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Global announcement cannot have a workspace.",
        )
    if scope_type == "workspace" and workspace_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Workspace announcement requires a workspace.",
        )

    item = Announcement(
        scope_type=scope_type,
        workspace_id=workspace_id,
        title=payload.title,
        body=payload.body,
        severity=payload.severity,
        pinned=payload.pinned,
        expires_at=_as_utc(payload.expires_at),
        created_by_user_id=actor.id,
        updated_by_user_id=actor.id,
    )
    item = await repository.create(db, item)
    record_audit_log(
        db,
        actor,
        "announcement.create",
        "announcement",
        item.id,
        item.title,
        {"scope_type": item.scope_type, "severity": item.severity},
        workspace_id=workspace_id,
    )
    await db.commit()
    return _announcement_response(item)


async def list_announcements(
    db: AsyncSession,
    *,
    scope_type: AnnouncementScope,
    workspace_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[AnnouncementResponse], int]:
    items = await repository.list_for_management(
        db,
        scope_type=scope_type,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )
    total = await repository.count_for_management(
        db,
        scope_type=scope_type,
        workspace_id=workspace_id,
    )
    return ([_announcement_response(item) for item in items], total)


async def update_announcement(
    db: AsyncSession,
    *,
    scope_type: AnnouncementScope,
    workspace_id: str | None,
    announcement_id: str,
    actor: User,
    payload: AnnouncementUpdateRequest,
    settings: Settings,
) -> AnnouncementResponse:
    item = await repository.get_by_id(
        db,
        announcement_id,
        scope_type=scope_type,
        workspace_id=workspace_id,
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found.")
    if item.status == "archived":
        raise HTTPException(status.HTTP_409_CONFLICT, "Archived announcement cannot be edited.")

    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        item.title = payload.title or ""
    if "body" in changes:
        item.body = payload.body or ""
    if "severity" in changes and payload.severity is not None:
        item.severity = payload.severity
    if "pinned" in changes and payload.pinned is not None:
        item.pinned = payload.pinned
    if "expires_at" in changes:
        item.expires_at = _validate_expiry(payload.expires_at, item.published_at)
    item.updated_by_user_id = actor.id
    item = await repository.save(db, item)
    record_audit_log(
        db,
        actor,
        "announcement.update",
        "announcement",
        item.id,
        item.title,
        {"status": item.status, "fields": sorted(changes)},
        workspace_id=workspace_id,
    )
    await db.commit()
    if item.status == "published":
        await _publish_live_event(settings, item, "announcement.updated")
    return _announcement_response(item)


async def publish_announcement(
    db: AsyncSession,
    *,
    scope_type: AnnouncementScope,
    workspace_id: str | None,
    announcement_id: str,
    actor: User,
    settings: Settings,
) -> AnnouncementResponse:
    item = await repository.get_by_id(
        db,
        announcement_id,
        scope_type=scope_type,
        workspace_id=workspace_id,
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found.")
    if item.status == "archived":
        raise HTTPException(status.HTTP_409_CONFLICT, "Archived announcement cannot be published.")
    if item.status != "published":
        now = utc_now()
        item.status = "published"
        item.published_at = now
        item.expires_at = _validate_expiry(item.expires_at, now)
        item.updated_by_user_id = actor.id
        item = await repository.save(db, item)
        record_audit_log(
            db,
            actor,
            "announcement.publish",
            "announcement",
            item.id,
            item.title,
            {"severity": item.severity},
            workspace_id=workspace_id,
        )
        await db.commit()
        await _publish_live_event(settings, item, "announcement.published")
    return _announcement_response(item)


async def archive_announcement(
    db: AsyncSession,
    *,
    scope_type: AnnouncementScope,
    workspace_id: str | None,
    announcement_id: str,
    actor: User,
    settings: Settings,
) -> AnnouncementResponse:
    item = await repository.get_by_id(
        db,
        announcement_id,
        scope_type=scope_type,
        workspace_id=workspace_id,
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found.")
    if item.status != "archived":
        item.status = "archived"
        item.updated_by_user_id = actor.id
        item = await repository.save(db, item)
        record_audit_log(
            db,
            actor,
            "announcement.archive",
            "announcement",
            item.id,
            item.title,
            {},
            workspace_id=workspace_id,
        )
        await db.commit()
        await _publish_live_event(settings, item, "announcement.archived")
    return _announcement_response(item)


async def list_messages(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str | None,
    limit: int,
    offset: int,
) -> tuple[list[AnnouncementMessageResponse], int]:
    now = utc_now()
    rows = await repository.list_visible_messages(
        db,
        user.id,
        workspace_id,
        now,
        limit,
        offset,
    )
    total = await repository.count_visible_messages(db, workspace_id, now)
    return ([_message_response(item, read) for item, read in rows], total)


async def get_unread_message_count(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str | None,
) -> int:
    return await repository.count_unread_messages(
        db,
        user.id,
        workspace_id,
        utc_now(),
    )


async def mark_message_read(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str | None,
    announcement_id: str,
) -> None:
    row = await repository.get_visible_message(
        db,
        user.id,
        workspace_id,
        announcement_id,
        utc_now(),
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    _item, existing = row
    if existing is None:
        await repository.save_read(
            db,
            AnnouncementRead(
                announcement_id=announcement_id,
                user_id=user.id,
            ),
        )
        await db.commit()


async def mark_all_messages_read(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: str | None,
) -> None:
    now = utc_now()
    announcement_ids = await repository.list_visible_ids(db, workspace_id, now)
    existing_ids = await repository.list_read_ids(db, user.id, announcement_ids)
    missing_reads = [
        AnnouncementRead(announcement_id=announcement_id, user_id=user.id)
        for announcement_id in announcement_ids
        if announcement_id not in existing_ids
    ]
    if missing_reads:
        await repository.create_reads(db, missing_reads)
        await db.commit()
