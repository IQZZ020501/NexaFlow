from datetime import datetime

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.announcements.models import (
    Announcement as AnnouncementOrm,
    AnnouncementRead as AnnouncementReadOrm,
)
from app.entities.announcements.models import Announcement, AnnouncementRead
from app.infra.db import mapping


def _visible_clauses(
    *,
    workspace_id: str | None,
    now: datetime,
) -> list:
    scopes = [AnnouncementOrm.scope_type == "global"]
    if workspace_id is not None:
        scopes.append(
            and_(
                AnnouncementOrm.scope_type == "workspace",
                AnnouncementOrm.workspace_id == workspace_id,
            )
        )
    return [
        or_(*scopes),
        AnnouncementOrm.status == "published",
        AnnouncementOrm.published_at.is_not(None),
        AnnouncementOrm.published_at <= now,
        or_(
            AnnouncementOrm.expires_at.is_(None),
            AnnouncementOrm.expires_at > now,
        ),
    ]


async def create(
    db: AsyncSession,
    announcement: Announcement,
) -> Announcement:
    row = AnnouncementOrm(**announcement.__dict__)
    db.add(row)
    await db.flush()
    return mapping.to_entity(Announcement, row)


async def save(
    db: AsyncSession,
    announcement: Announcement,
) -> Announcement:
    row = await mapping.save(db, AnnouncementOrm, announcement)
    return mapping.to_entity(Announcement, row)


async def get_by_id(
    db: AsyncSession,
    announcement_id: str,
    *,
    scope_type: str | None = None,
    workspace_id: str | None = None,
) -> Announcement | None:
    statement = select(AnnouncementOrm).where(AnnouncementOrm.id == announcement_id)
    if scope_type is not None:
        statement = statement.where(AnnouncementOrm.scope_type == scope_type)
    if workspace_id is not None:
        statement = statement.where(AnnouncementOrm.workspace_id == workspace_id)
    row = await db.scalar(statement)
    return mapping.to_entity(Announcement, row) if row is not None else None


async def list_for_management(
    db: AsyncSession,
    *,
    scope_type: str,
    workspace_id: str | None,
    limit: int,
    offset: int,
) -> list[Announcement]:
    statement = (
        select(AnnouncementOrm)
        .where(
            AnnouncementOrm.scope_type == scope_type,
            AnnouncementOrm.workspace_id == workspace_id,
        )
        .order_by(
            desc(AnnouncementOrm.pinned),
            desc(AnnouncementOrm.created_at),
            desc(AnnouncementOrm.id),
        )
        .limit(limit)
        .offset(offset)
    )
    rows = await db.scalars(statement)
    return [mapping.to_entity(Announcement, row) for row in rows.all()]


async def count_for_management(
    db: AsyncSession,
    *,
    scope_type: str,
    workspace_id: str | None,
) -> int:
    statement = select(func.count()).select_from(AnnouncementOrm).where(
        AnnouncementOrm.scope_type == scope_type,
        AnnouncementOrm.workspace_id == workspace_id,
    )
    return int(await db.scalar(statement) or 0)


async def list_visible_messages(
    db: AsyncSession,
    user_id: str,
    workspace_id: str | None,
    now: datetime,
    limit: int,
    offset: int,
) -> list[tuple[Announcement, AnnouncementRead | None]]:
    read_join = and_(
        AnnouncementReadOrm.announcement_id == AnnouncementOrm.id,
        AnnouncementReadOrm.user_id == user_id,
    )
    result = await db.execute(
        select(AnnouncementOrm, AnnouncementReadOrm)
        .outerjoin(AnnouncementReadOrm, read_join)
        .where(*_visible_clauses(workspace_id=workspace_id, now=now))
        .order_by(
            desc(AnnouncementOrm.pinned),
            desc(AnnouncementOrm.published_at),
            desc(AnnouncementOrm.id),
        )
        .limit(limit)
        .offset(offset)
    )
    return [
        (
            mapping.to_entity(Announcement, announcement),
            mapping.to_entity(AnnouncementRead, read) if read is not None else None,
        )
        for announcement, read in result.all()
    ]


async def count_visible_messages(
    db: AsyncSession,
    workspace_id: str | None,
    now: datetime,
) -> int:
    statement = select(func.count()).select_from(AnnouncementOrm).where(
        *_visible_clauses(workspace_id=workspace_id, now=now)
    )
    return int(await db.scalar(statement) or 0)


async def count_unread_messages(
    db: AsyncSession,
    user_id: str,
    workspace_id: str | None,
    now: datetime,
) -> int:
    read_join = and_(
        AnnouncementReadOrm.announcement_id == AnnouncementOrm.id,
        AnnouncementReadOrm.user_id == user_id,
    )
    statement = (
        select(func.count())
        .select_from(AnnouncementOrm)
        .outerjoin(AnnouncementReadOrm, read_join)
        .where(
            *_visible_clauses(workspace_id=workspace_id, now=now),
            AnnouncementReadOrm.announcement_id.is_(None),
        )
    )
    return int(await db.scalar(statement) or 0)


async def get_visible_message(
    db: AsyncSession,
    user_id: str,
    workspace_id: str | None,
    announcement_id: str,
    now: datetime,
) -> tuple[Announcement, AnnouncementRead | None] | None:
    read_join = and_(
        AnnouncementReadOrm.announcement_id == AnnouncementOrm.id,
        AnnouncementReadOrm.user_id == user_id,
    )
    result = await db.execute(
        select(AnnouncementOrm, AnnouncementReadOrm)
        .outerjoin(AnnouncementReadOrm, read_join)
        .where(
            AnnouncementOrm.id == announcement_id,
            *_visible_clauses(workspace_id=workspace_id, now=now),
        )
    )
    row = result.one_or_none()
    if row is None:
        return None
    announcement, read = row
    return (
        mapping.to_entity(Announcement, announcement),
        mapping.to_entity(AnnouncementRead, read) if read is not None else None,
    )


async def list_visible_ids(
    db: AsyncSession,
    workspace_id: str | None,
    now: datetime,
) -> list[str]:
    rows = await db.scalars(
        select(AnnouncementOrm.id)
        .where(*_visible_clauses(workspace_id=workspace_id, now=now))
        .order_by(AnnouncementOrm.id)
    )
    return list(rows.all())


async def get_read(
    db: AsyncSession,
    user_id: str,
    announcement_id: str,
) -> AnnouncementRead | None:
    row = await db.scalar(
        select(AnnouncementReadOrm).where(
            AnnouncementReadOrm.user_id == user_id,
            AnnouncementReadOrm.announcement_id == announcement_id,
        )
    )
    return mapping.to_entity(AnnouncementRead, row) if row is not None else None


async def save_read(
    db: AsyncSession,
    read: AnnouncementRead,
) -> AnnouncementRead:
    row = await db.scalar(
        select(AnnouncementReadOrm).where(
            AnnouncementReadOrm.user_id == read.user_id,
            AnnouncementReadOrm.announcement_id == read.announcement_id,
        )
    )
    if row is None:
        row = AnnouncementReadOrm(**read.__dict__)
        db.add(row)
    else:
        row.read_at = read.read_at
        row.dismissed_at = read.dismissed_at
    await db.flush()
    return mapping.to_entity(AnnouncementRead, row)


async def create_reads(
    db: AsyncSession,
    reads: list[AnnouncementRead],
) -> None:
    if not reads:
        return
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(AnnouncementReadOrm)
    elif dialect == "sqlite":
        statement = sqlite_insert(AnnouncementReadOrm)
    else:
        raise RuntimeError(f"Unsupported announcement read dialect: {dialect}")
    await db.execute(
        statement.values([read.__dict__ for read in reads]).on_conflict_do_nothing(
            index_elements=("announcement_id", "user_id")
        )
    )


async def list_read_ids(
    db: AsyncSession,
    user_id: str,
    announcement_ids: list[str],
) -> set[str]:
    if not announcement_ids:
        return set()
    rows = await db.scalars(
        select(AnnouncementReadOrm.announcement_id).where(
            AnnouncementReadOrm.user_id == user_id,
            AnnouncementReadOrm.announcement_id.in_(announcement_ids),
        )
    )
    return set(rows.all())
