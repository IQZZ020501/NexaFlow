from datetime import datetime
from pathlib import Path

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    CHUNK_INDEXED_STATUS,
    DOCUMENT_DELETED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    DOCUMENT_STAGED_META_KEY,
    TASK_FAILED_STATUS,
    TASK_CANCELLING_STATUS,
    TASK_GRAPH_REBUILD,
    TASK_GRAPH_SYNC,
    TASK_QUEUED_STATUS,
    TASK_RUNNING_STATUS,
    VISIBLE_DOCUMENT_STATUSES,
    KnowledgeAsset,
    KnowledgeAttachment,
    KnowledgeBase,
    KnowledgeChunkAsset,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeStorageCleanup,
    KnowledgeTask,
)
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.entities.defaults import new_id, utc_now
from app.infra.db.mapping import (
    refresh_entity,
    save,
    to_entity,
    to_orm,
)
from app.domain.platform.models import ResourcePermission as ResourcePermissionORM
from app.domain.knowledge.models import (
    KnowledgeAsset as KnowledgeAssetORM,
    KnowledgeAttachment as KnowledgeAttachmentORM,
    KnowledgeBase as KnowledgeBaseORM,
    KnowledgeChunkAsset as KnowledgeChunkAssetORM,
    KnowledgeDocument as KnowledgeDocumentORM,
    KnowledgeDocumentChunk as KnowledgeDocumentChunkORM,
    KnowledgeDocumentParentChunk as KnowledgeDocumentParentChunkORM,
    KnowledgeDocumentReference as KnowledgeDocumentReferenceORM,
    KnowledgeEvaluationCase as KnowledgeEvaluationCaseORM,
    KnowledgeStorageCleanup as KnowledgeStorageCleanupORM,
    KnowledgeTask as KnowledgeTaskORM,
)

_QUERY_KEYWORD_CHUNK_IDS = text(
    (
        Path(__file__).parent.parent.parent
        / "sql"
        / "knowledge"
        / "query_keyword_chunk_ids.sql"
    ).read_text(encoding="utf-8")
)



async def create_knowledge_storage_cleanup(
    db: AsyncSession,
    entity: KnowledgeStorageCleanup,
) -> KnowledgeStorageCleanup:
    row = await save(db, KnowledgeStorageCleanupORM, entity)
    return to_entity(KnowledgeStorageCleanup, row)

async def lock_knowledge_storage_cleanup(
    db: AsyncSession,
    cleanup_id: str,
) -> KnowledgeStorageCleanup | None:
    row = await db.scalar(
        select(KnowledgeStorageCleanupORM)
        .where(KnowledgeStorageCleanupORM.id == cleanup_id)
        .with_for_update()
    )
    return to_entity(KnowledgeStorageCleanup, row) if row else None

async def list_due_knowledge_storage_cleanup_ids(
    db: AsyncSession,
    due_at: datetime,
    limit: int = 100,
) -> list[str]:
    result = await db.scalars(
        select(KnowledgeStorageCleanupORM.id)
        .where(KnowledgeStorageCleanupORM.next_attempt_at <= due_at)
        .order_by(
            KnowledgeStorageCleanupORM.next_attempt_at,
            KnowledgeStorageCleanupORM.id,
        )
        .limit(limit)
    )
    return list(result.all())

async def save_knowledge_storage_cleanup(
    db: AsyncSession,
    entity: KnowledgeStorageCleanup,
) -> None:
    await save(db, KnowledgeStorageCleanupORM, entity)

async def delete_knowledge_storage_cleanup(
    db: AsyncSession,
    cleanup_id: str,
) -> None:
    await db.execute(
        delete(KnowledgeStorageCleanupORM).where(
            KnowledgeStorageCleanupORM.id == cleanup_id
        )
    )

