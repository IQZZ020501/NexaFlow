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



async def list_knowledge_bases_with_user_grants(
    db: AsyncSession,
    workspace_id: str,
    knowledge_base_ids: list[str],
    user_id: str,
    resource_type: str,
) -> list[tuple[KnowledgeBase, ResourcePermission | None]]:
    if not knowledge_base_ids:
        return []
    grant = ResourcePermissionORM
    rows = await db.execute(
        select(KnowledgeBaseORM, grant)
        .outerjoin(
            grant,
            (
                (grant.workspace_id == KnowledgeBaseORM.workspace_id)
                & (grant.resource_type == resource_type)
                & (grant.resource_id == KnowledgeBaseORM.id)
                & (grant.user_id == user_id)
            ),
        )
        .where(
            KnowledgeBaseORM.workspace_id == workspace_id,
            KnowledgeBaseORM.id.in_(knowledge_base_ids),
        )
    )
    return [
        (
            to_entity(KnowledgeBase, knowledge_base),
            to_entity(ResourcePermission, permission) if permission else None,
        )
        for knowledge_base, permission in rows.all()
    ]

async def list_and_lock_knowledge_bases_in_workspace(
    db: AsyncSession,
    workspace_id: str,
) -> list[KnowledgeBase]:
    result = await db.scalars(
        select(KnowledgeBaseORM)
        .where(KnowledgeBaseORM.workspace_id == workspace_id)
        .order_by(KnowledgeBaseORM.id)
        .with_for_update()
    )
    return [to_entity(KnowledgeBase, row) for row in result.all()]

async def get_knowledge_base_by_id(
    db: AsyncSession,
    knowledge_base_id: str,
) -> KnowledgeBase | None:
    row = await db.get(KnowledgeBaseORM, knowledge_base_id)
    return to_entity(KnowledgeBase, row) if row else None

async def lock_knowledge_base(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeBase | None:
    row = await db.scalar(
        select(KnowledgeBaseORM)
        .where(KnowledgeBaseORM.id == knowledge_base.id)
        .with_for_update()
    )
    return to_entity(KnowledgeBase, row) if row else None

async def create_knowledge_base(
    db: AsyncSession,
    entity: KnowledgeBase,
) -> KnowledgeBase:
    row = await save(db, KnowledgeBaseORM, entity)
    return to_entity(KnowledgeBase, row)

async def save_knowledge_base(
    db: AsyncSession,
    entity: KnowledgeBase,
) -> None:
    await save(db, KnowledgeBaseORM, entity)

async def set_knowledge_base_embedding_model_id(
    db: AsyncSession,
    knowledge_base_id: str,
    embedding_model_id: str,
) -> None:
    await db.execute(
        update(KnowledgeBaseORM)
        .where(KnowledgeBaseORM.id == knowledge_base_id)
        .values(
            embedding_model_id=embedding_model_id,
            updated_at=utc_now(),
        )
    )

async def refresh_knowledge_base(
    db: AsyncSession,
    entity: KnowledgeBase,
) -> KnowledgeBase:
    return await refresh_entity(db, KnowledgeBaseORM, KnowledgeBase, entity)

async def delete_knowledge_base(db: AsyncSession, entity: KnowledgeBase) -> None:
    row = await db.get(KnowledgeBaseORM, entity.id)
    if row is not None:
        await db.delete(row)

async def delete_knowledge_base_graph(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    resource_type: str,
) -> None:
    await db.execute(
        delete(KnowledgeEvaluationCaseORM).where(
            KnowledgeEvaluationCaseORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeEvaluationCaseORM.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeDocumentReferenceORM).where(
            KnowledgeDocumentReferenceORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentReferenceORM.knowledge_base_id
            == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeTaskORM).where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeChunkAssetORM).where(
            KnowledgeChunkAssetORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeChunkAssetORM.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeDocumentChunkORM).where(
            KnowledgeDocumentChunkORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunkORM.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeDocumentParentChunkORM).where(
            KnowledgeDocumentParentChunkORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentParentChunkORM.knowledge_base_id
            == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeAssetORM).where(
            KnowledgeAssetORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeAssetORM.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeDocumentORM).where(
            KnowledgeDocumentORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentORM.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeAttachmentORM).where(
            KnowledgeAttachmentORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeAttachmentORM.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == knowledge_base.workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeBaseORM).where(KnowledgeBaseORM.id == knowledge_base.id)
    )

