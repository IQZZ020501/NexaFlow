"""Bounded knowledge lists; totals and status counts cover the whole scope."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.knowledge.models import KnowledgeDocument as DocumentOrm
from app.domain.knowledge.models import KnowledgeDocumentChunk as ChunkOrm
from app.domain.knowledge.models import KnowledgeTask as TaskOrm
from app.entities.knowledge import (
    DOCUMENT_DELETED_STATUS,
    DOCUMENT_STAGED_META_KEY,
    TASK_CANCELLING_STATUS,
    TASK_QUEUED_STATUS,
    TASK_RUNNING_STATUS,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeTask,
)
from app.infra.db.mapping import to_entity
from app.infra.db.repositories.knowledge.documents import _visible_document_conditions

OPEN_TASK_STATUSES = (TASK_QUEUED_STATUS, TASK_RUNNING_STATUS, TASK_CANCELLING_STATUS)


async def document_page(
    db: AsyncSession,
    kb: KnowledgeBase,
    *,
    limit: int,
    offset: int,
    search: str,
    sort_by: str,
    sort_direction: str,
    include_staged: bool,
) -> tuple[list[KnowledgeDocument], int, dict[str, int]]:
    scope = [
        DocumentOrm.workspace_id == kb.workspace_id,
        DocumentOrm.knowledge_base_id == kb.id,
        DocumentOrm.status != DOCUMENT_DELETED_STATUS,
    ]
    if not include_staged:
        scope.append(_visible_document_conditions(DocumentOrm))
    statuses = dict(
        (
            await db.execute(
                select(DocumentOrm.status, func.count())
                .where(*scope)
                .group_by(DocumentOrm.status)
            )
        ).all()
    )
    if search.strip():
        scope.append(
            func.lower(DocumentOrm.filename).contains(
                search.strip().lower(), autoescape=True
            )
        )
    total = await db.scalar(select(func.count()).select_from(DocumentOrm).where(*scope))
    columns = {
        "filename": func.lower(DocumentOrm.filename),
        "created_at": DocumentOrm.created_at,
        "updated_at": DocumentOrm.updated_at,
        "size_bytes": DocumentOrm.size_bytes,
        "chunk_count": select(func.count())
        .where(
            ChunkOrm.workspace_id == kb.workspace_id,
            ChunkOrm.knowledge_base_id == kb.id,
            ChunkOrm.document_id == DocumentOrm.id,
        )
        .correlate(DocumentOrm)
        .scalar_subquery(),
    }
    column = columns[sort_by]
    order = (
        (column.asc(), DocumentOrm.id.asc())
        if sort_direction == "asc"
        else (column.desc(), DocumentOrm.id.desc())
    )
    rows = await db.scalars(
        select(DocumentOrm).where(*scope).order_by(*order).limit(limit).offset(offset)
    )
    return (
        [to_entity(KnowledgeDocument, row) for row in rows],
        int(total or 0),
        statuses,
    )


def task_scope(kb: KnowledgeBase, exclude_staged: bool):
    scope = [
        TaskOrm.workspace_id == kb.workspace_id,
        TaskOrm.knowledge_base_id == kb.id,
    ]
    if exclude_staged:
        staged = select(DocumentOrm.id).where(
            DocumentOrm.workspace_id == kb.workspace_id,
            DocumentOrm.knowledge_base_id == kb.id,
            DocumentOrm.meta[DOCUMENT_STAGED_META_KEY].as_boolean().is_(True),
        )
        scope.append(
            or_(TaskOrm.document_id.is_(None), TaskOrm.document_id.not_in(staged))
        )
    return scope


async def task_page(
    db: AsyncSession,
    kb: KnowledgeBase,
    *,
    limit: int,
    offset: int,
    exclude_staged: bool,
):
    scope = task_scope(kb, exclude_staged)
    total = await db.scalar(select(func.count()).select_from(TaskOrm).where(*scope))
    processing = await db.scalar(
        select(func.count())
        .select_from(TaskOrm)
        .where(
            *scope,
            TaskOrm.status.in_(OPEN_TASK_STATUSES),
        )
    )
    rows = await db.execute(
        select(TaskOrm, DocumentOrm.filename)
        .outerjoin(
            DocumentOrm,
            and_(
                DocumentOrm.id == TaskOrm.document_id,
                DocumentOrm.workspace_id == kb.workspace_id,
                DocumentOrm.knowledge_base_id == kb.id,
                DocumentOrm.status != DOCUMENT_DELETED_STATUS,
            ),
        )
        .where(*scope)
        .order_by(TaskOrm.created_at.desc(), TaskOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return (
        [(to_entity(KnowledgeTask, row), filename) for row, filename in rows],
        int(total or 0),
        bool(processing),
    )


async def document_tasks(
    db: AsyncSession, kb: KnowledgeBase, document_ids: list[str]
) -> list[KnowledgeTask]:
    if not document_ids:
        return []
    rows = await db.scalars(
        select(TaskOrm)
        .where(
            *task_scope(kb, False),
            TaskOrm.document_id.in_(document_ids),
            TaskOrm.status.in_(OPEN_TASK_STATUSES),
        )
        .order_by(TaskOrm.created_at.desc(), TaskOrm.id.desc())
    )
    return [to_entity(KnowledgeTask, row) for row in rows]


async def document_options(db: AsyncSession, kb: KnowledgeBase):
    rows = await db.execute(
        select(DocumentOrm.id, DocumentOrm.filename, DocumentOrm.is_active)
        .where(
            DocumentOrm.workspace_id == kb.workspace_id,
            DocumentOrm.knowledge_base_id == kb.id,
            _visible_document_conditions(DocumentOrm),
        )
        .order_by(DocumentOrm.filename, DocumentOrm.id)
    )
    return [dict(row._mapping) for row in rows]
