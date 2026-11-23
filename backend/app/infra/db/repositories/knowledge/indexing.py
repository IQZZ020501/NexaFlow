"""Scoped selection and persistence for knowledge-wide indexing."""

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.knowledge.models import KnowledgeDocument as DocumentORM
from app.domain.knowledge.models import KnowledgeDocumentChunk as ChunkORM
from app.domain.knowledge.models import KnowledgeTask as TaskORM
from app.entities.defaults import utc_now
from app.entities.knowledge import (
    DOCUMENT_INDEX_QUEUED_STATUS,
    TASK_CANCELLING_STATUS,
    TASK_QUEUED_STATUS,
    TASK_RUNNING_STATUS,
    KnowledgeBase,
    KnowledgeTask,
)
from app.infra.db.mapping import to_orm
from app.infra.db.repositories.knowledge.documents import _visible_document_conditions


async def list_batch_index_documents(
    db: AsyncSession, knowledge_base: KnowledgeBase, statuses: set[str]
) -> list[tuple[str, int]]:
    open_task = exists(
        select(TaskORM.id).where(
            TaskORM.workspace_id == knowledge_base.workspace_id,
            TaskORM.knowledge_base_id == knowledge_base.id,
            TaskORM.document_id == DocumentORM.id,
            TaskORM.status.in_(
                {TASK_QUEUED_STATUS, TASK_RUNNING_STATUS, TASK_CANCELLING_STATUS}
            ),
        )
    )
    rows = await db.execute(
        select(DocumentORM.id, func.count(ChunkORM.id))
        .join(
            ChunkORM,
            (
                (ChunkORM.workspace_id == DocumentORM.workspace_id)
                & (ChunkORM.knowledge_base_id == DocumentORM.knowledge_base_id)
                & (ChunkORM.document_id == DocumentORM.id)
            ),
        )
        .where(
            DocumentORM.workspace_id == knowledge_base.workspace_id,
            DocumentORM.knowledge_base_id == knowledge_base.id,
            *_visible_document_conditions(DocumentORM),
            DocumentORM.status.in_(statuses),
            ~open_task,
        )
        .group_by(DocumentORM.id)
        .order_by(DocumentORM.id)
    )
    return [(document_id, count) for document_id, count in rows]


async def create_batch_index_tasks(
    db: AsyncSession, knowledge_base: KnowledgeBase, tasks: list[KnowledgeTask]
) -> None:
    # Bound IN lists and flushes while keeping the caller's single transaction.
    for start in range(0, len(tasks), 500):
        batch = tasks[start : start + 500]
        db.add_all([to_orm(TaskORM, task) for task in batch])
        await db.execute(
            update(DocumentORM)
            .where(
                DocumentORM.workspace_id == knowledge_base.workspace_id,
                DocumentORM.knowledge_base_id == knowledge_base.id,
                DocumentORM.id.in_([task.document_id for task in batch]),
            )
            .values(
                status=DOCUMENT_INDEX_QUEUED_STATUS,
                last_error=None,
                updated_at=utc_now(),
            )
        )
        await db.flush()
