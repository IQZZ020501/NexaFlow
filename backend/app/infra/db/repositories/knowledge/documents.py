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



def _visible_document_conditions(document: KnowledgeDocumentORM):
    """Visibility predicate shared by document listing and stats aggregation."""
    return and_(
        document.status.in_(VISIBLE_DOCUMENT_STATUSES),
        document.meta[DOCUMENT_STAGED_META_KEY].as_boolean().is_not(True),
    )

async def list_knowledge_base_rows(
    db: AsyncSession,
    workspace_id: str,
    actor_id: str,
    resource_type: str,
    include_all: bool,
    limit: int | None = None,
    offset: int = 0,
) -> list[tuple[KnowledgeBase, ResourcePermission | None, int, int]]:
    grant = ResourcePermissionORM
    document_stats = (
        select(
            KnowledgeDocumentORM.knowledge_base_id.label("knowledge_base_id"),
            func.count(KnowledgeDocumentORM.id.distinct()).label("document_count"),
            func.coalesce(func.sum(KnowledgeDocumentChunkORM.char_count), 0).label(
                "char_count"
            ),
        )
        .outerjoin(
            KnowledgeDocumentChunkORM,
            (
                (KnowledgeDocumentChunkORM.workspace_id == KnowledgeDocumentORM.workspace_id)
                & (
                    KnowledgeDocumentChunkORM.knowledge_base_id
                    == KnowledgeDocumentORM.knowledge_base_id
                )
                & (KnowledgeDocumentChunkORM.document_id == KnowledgeDocumentORM.id)
            ),
        )
        .where(
            KnowledgeDocumentORM.workspace_id == workspace_id,
            *_visible_document_conditions(KnowledgeDocumentORM),
        )
        .group_by(KnowledgeDocumentORM.knowledge_base_id)
        .subquery()
    )
    statement = select(
        KnowledgeBaseORM,
        grant,
        func.coalesce(document_stats.c.document_count, 0),
        func.coalesce(document_stats.c.char_count, 0),
    ).outerjoin(
        grant,
        (
            (grant.workspace_id == KnowledgeBaseORM.workspace_id)
            & (grant.resource_type == resource_type)
            & (grant.resource_id == KnowledgeBaseORM.id)
            & (grant.user_id == actor_id)
        ),
    ).outerjoin(
        document_stats,
        document_stats.c.knowledge_base_id == KnowledgeBaseORM.id,
    ).where(KnowledgeBaseORM.workspace_id == workspace_id)

    if not include_all:
        statement = statement.where(
            or_(
                KnowledgeBaseORM.created_by_user_id == actor_id,
                grant.id.is_not(None),
            )
        )

    statement = statement.order_by(
        KnowledgeBaseORM.created_at.desc(),
        KnowledgeBaseORM.id.desc(),
    )
    result = await db.execute(statement.limit(limit).offset(offset))
    return [
        (
            to_entity(KnowledgeBase, knowledge_base),
            to_entity(ResourcePermission, permission) if permission else None,
            int(document_count),
            int(char_count),
        )
        for knowledge_base, permission, document_count, char_count in result.all()
    ]

async def list_knowledge_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    include_staged: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeDocument]:
    statement = select(KnowledgeDocumentORM).where(
        KnowledgeDocumentORM.workspace_id == knowledge_base.workspace_id,
        KnowledgeDocumentORM.knowledge_base_id == knowledge_base.id,
        KnowledgeDocumentORM.status != DOCUMENT_DELETED_STATUS,
    )
    if not include_staged:
        statement = statement.where(*_visible_document_conditions(KnowledgeDocumentORM))
    statement = statement.order_by(
        KnowledgeDocumentORM.created_at.desc(),
        KnowledgeDocumentORM.id.desc(),
    )
    result = await db.scalars(statement.limit(limit).offset(offset))
    return [to_entity(KnowledgeDocument, row) for row in result]

async def has_indexed_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> bool:
    count = await db.scalar(
        select(func.count())
        .select_from(KnowledgeDocumentORM)
        .where(
            KnowledgeDocumentORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentORM.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentORM.status == DOCUMENT_INDEXED_STATUS,
            KnowledgeDocumentORM.is_active.is_(True),
        )
    )
    return bool(count)

async def get_knowledge_document_by_id(
    db: AsyncSession,
    document_id: str,
) -> KnowledgeDocument | None:
    row = await db.get(KnowledgeDocumentORM, document_id)
    return to_entity(KnowledgeDocument, row) if row else None

async def create_knowledge_document(
    db: AsyncSession,
    entity: KnowledgeDocument,
) -> KnowledgeDocument:
    row = await save(db, KnowledgeDocumentORM, entity)
    return to_entity(KnowledgeDocument, row)

async def save_knowledge_document(
    db: AsyncSession,
    entity: KnowledgeDocument,
) -> None:
    await save(db, KnowledgeDocumentORM, entity)

async def refresh_knowledge_document(
    db: AsyncSession,
    entity: KnowledgeDocument,
) -> KnowledgeDocument:
    return await refresh_entity(db, KnowledgeDocumentORM, KnowledgeDocument, entity)

async def delete_knowledge_document(db: AsyncSession, entity: KnowledgeDocument) -> None:
    row = await db.get(KnowledgeDocumentORM, entity.id)
    if row is not None:
        await db.delete(row)

async def get_knowledge_attachment_by_id(
    db: AsyncSession,
    attachment_id: str,
) -> KnowledgeAttachment | None:
    row = await db.get(KnowledgeAttachmentORM, attachment_id)
    return to_entity(KnowledgeAttachment, row) if row else None

async def create_knowledge_attachment(
    db: AsyncSession,
    entity: KnowledgeAttachment,
) -> KnowledgeAttachment:
    row = await save(db, KnowledgeAttachmentORM, entity)
    return to_entity(KnowledgeAttachment, row)

async def save_knowledge_attachment(
    db: AsyncSession,
    entity: KnowledgeAttachment,
) -> None:
    await save(db, KnowledgeAttachmentORM, entity)

async def refresh_knowledge_attachment(
    db: AsyncSession,
    entity: KnowledgeAttachment,
) -> KnowledgeAttachment:
    return await refresh_entity(
        db,
        KnowledgeAttachmentORM,
        KnowledgeAttachment,
        entity,
    )

async def delete_knowledge_attachment(
    db: AsyncSession,
    entity: KnowledgeAttachment,
) -> None:
    row = await db.get(KnowledgeAttachmentORM, entity.id)
    if row is not None:
        await db.delete(row)

async def lock_knowledge_attachments(
    db: AsyncSession,
    attachment_ids: list[str],
) -> list[KnowledgeAttachment]:
    result = await db.scalars(
        select(KnowledgeAttachmentORM)
        .where(KnowledgeAttachmentORM.id.in_(attachment_ids))
        .with_for_update()
    )
    return [to_entity(KnowledgeAttachment, row) for row in result]

async def list_document_assets(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
) -> list[KnowledgeAsset]:
    result = await db.scalars(
        select(KnowledgeAssetORM)
        .where(
            KnowledgeAssetORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeAssetORM.knowledge_base_id == knowledge_base.id,
            KnowledgeAssetORM.document_id == document_id,
        )
        .order_by(KnowledgeAssetORM.asset_index, KnowledgeAssetORM.id)
    )
    return [to_entity(KnowledgeAsset, row) for row in result]

async def get_document_asset(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
    asset_id: str,
) -> KnowledgeAsset | None:
    row = await db.scalar(
        select(KnowledgeAssetORM).where(
            KnowledgeAssetORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeAssetORM.knowledge_base_id == knowledge_base.id,
            KnowledgeAssetORM.document_id == document_id,
            KnowledgeAssetORM.id == asset_id,
        )
    )
    return to_entity(KnowledgeAsset, row) if row else None

async def list_chunk_assets(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    chunk_ids: set[str],
) -> list[tuple[KnowledgeChunkAsset, KnowledgeAsset]]:
    if not chunk_ids:
        return []
    result = await db.execute(
        select(KnowledgeChunkAssetORM, KnowledgeAssetORM)
        .join(
            KnowledgeAssetORM,
            KnowledgeAssetORM.id == KnowledgeChunkAssetORM.asset_id,
        )
        .where(
            KnowledgeChunkAssetORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeChunkAssetORM.knowledge_base_id == knowledge_base.id,
            KnowledgeChunkAssetORM.chunk_id.in_(chunk_ids),
        )
        .order_by(
            KnowledgeChunkAssetORM.chunk_id,
            KnowledgeChunkAssetORM.asset_index,
        )
    )
    return [
        (
            to_entity(KnowledgeChunkAsset, chunk_asset),
            to_entity(KnowledgeAsset, asset),
        )
        for chunk_asset, asset in result.all()
    ]

async def delete_document_assets(db: AsyncSession, document_id: str) -> list[str]:
    object_keys = list(
        await db.scalars(
            select(KnowledgeAssetORM.object_key).where(
                KnowledgeAssetORM.document_id == document_id
            )
        )
    )
    await db.execute(
        delete(KnowledgeChunkAssetORM).where(
            KnowledgeChunkAssetORM.document_id == document_id
        )
    )
    await db.execute(
        delete(KnowledgeAssetORM).where(KnowledgeAssetORM.document_id == document_id)
    )
    return object_keys

async def count_document_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> dict[str, int]:
    result = await db.execute(
        select(KnowledgeDocumentChunkORM.document_id, func.count())
        .where(
            KnowledgeDocumentChunkORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunkORM.knowledge_base_id == knowledge_base.id,
        )
        .group_by(KnowledgeDocumentChunkORM.document_id)
    )
    return dict(result.all())

async def list_document_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeDocumentChunk]:
    result = await db.scalars(
        select(KnowledgeDocumentChunkORM)
        .where(
            KnowledgeDocumentChunkORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunkORM.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentChunkORM.document_id == document_id,
        )
        .order_by(
            KnowledgeDocumentChunkORM.chunk_index,
            KnowledgeDocumentChunkORM.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(KnowledgeDocumentChunk, row) for row in result]

async def list_indexable_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str | None = None,
    statuses: set[str] | None = None,
) -> list[KnowledgeDocumentChunk]:
    statement = select(KnowledgeDocumentChunkORM).where(
        KnowledgeDocumentChunkORM.workspace_id == knowledge_base.workspace_id,
        KnowledgeDocumentChunkORM.knowledge_base_id == knowledge_base.id,
    )
    if document_id is not None:
        statement = statement.where(
            KnowledgeDocumentChunkORM.document_id == document_id
        )
    if statuses is not None:
        statement = statement.where(KnowledgeDocumentChunkORM.status.in_(statuses))
    result = await db.scalars(
        statement.order_by(
            KnowledgeDocumentChunkORM.document_id,
            KnowledgeDocumentChunkORM.chunk_index,
        )
    )
    return [to_entity(KnowledgeDocumentChunk, row) for row in result]

async def list_chunks_for_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_ids: set[str],
) -> list[KnowledgeDocumentChunk]:
    if not document_ids:
        return []
    result = await db.scalars(
        select(KnowledgeDocumentChunkORM)
        .where(
            KnowledgeDocumentChunkORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunkORM.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentChunkORM.document_id.in_(sorted(document_ids)),
        )
        .order_by(
            KnowledgeDocumentChunkORM.document_id,
            KnowledgeDocumentChunkORM.chunk_index,
        )
    )
    return [to_entity(KnowledgeDocumentChunk, row) for row in result]

async def save_knowledge_document_chunk(
    db: AsyncSession,
    entity: KnowledgeDocumentChunk,
) -> None:
    await save(db, KnowledgeDocumentChunkORM, entity)

async def replace_document_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
    parents: list[KnowledgeDocumentParentChunk],
    children: list[KnowledgeDocumentChunk],
    assets: list[KnowledgeAsset],
    chunk_asset_links: list[tuple[str, str, int]],
) -> None:
    """Persist a full preview replacement for a document.

    Rows are flushed in dependency order (assets, then parents, then chunks,
    then chunk-asset links) because the composite foreign keys are not
    inferable by SQLAlchemy's unit of work. The caller (orchestration) owns
    storage writes and validation; commit is coordinated by the caller.
    """
    if assets:
        for asset in assets:
            db.add(to_orm(KnowledgeAssetORM, asset))
        await db.flush()
    if parents:
        for parent in parents:
            db.add(to_orm(KnowledgeDocumentParentChunkORM, parent))
        await db.flush()
    if children:
        for chunk in children:
            db.add(to_orm(KnowledgeDocumentChunkORM, chunk))
        await db.flush()
    for chunk_id, asset_id, asset_index in chunk_asset_links:
        db.add(
            KnowledgeChunkAssetORM(
                id=new_id(),
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document_id,
                chunk_id=chunk_id,
                asset_id=asset_id,
                asset_index=asset_index,
            )
        )
    if chunk_asset_links:
        await db.flush()

async def list_chunks_by_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    chunk_ids: list[str],
) -> list[KnowledgeDocumentChunk]:
    if not chunk_ids:
        return []
    result = await db.scalars(
        select(KnowledgeDocumentChunkORM).where(
            KnowledgeDocumentChunkORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunkORM.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentChunkORM.status == CHUNK_INDEXED_STATUS,
            KnowledgeDocumentChunkORM.id.in_(chunk_ids),
        )
    )
    return [to_entity(KnowledgeDocumentChunk, row) for row in result]

async def list_parent_chunks_by_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    parent_ids: set[str],
) -> list[KnowledgeDocumentParentChunk]:
    if not parent_ids:
        return []
    result = await db.scalars(
        select(KnowledgeDocumentParentChunkORM).where(
            KnowledgeDocumentParentChunkORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeDocumentParentChunkORM.knowledge_base_id
            == knowledge_base.id,
            KnowledgeDocumentParentChunkORM.id.in_(parent_ids),
        )
    )
    return [to_entity(KnowledgeDocumentParentChunk, row) for row in result]

async def list_active_documents_by_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_ids: set[str],
) -> list[KnowledgeDocument]:
    if not document_ids:
        return []
    result = await db.scalars(
        select(KnowledgeDocumentORM).where(
            KnowledgeDocumentORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentORM.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentORM.id.in_(document_ids),
            KnowledgeDocumentORM.status != DOCUMENT_DELETED_STATUS,
            KnowledgeDocumentORM.is_active.is_(True),
        )
    )
    return [to_entity(KnowledgeDocument, row) for row in result]

async def list_retrievable_document_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_ids: set[str],
) -> set[str]:
    active_document_ids = {
        document.id
        for document in await list_active_documents_by_ids(
            db,
            knowledge_base,
            document_ids,
        )
    }
    if not active_document_ids:
        return set()
    rows = await db.scalars(
        select(KnowledgeDocumentChunkORM.document_id)
        .where(
            KnowledgeDocumentChunkORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunkORM.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentChunkORM.status == CHUNK_INDEXED_STATUS,
            KnowledgeDocumentChunkORM.document_id.in_(active_document_ids),
        )
        .distinct()
    )
    return set(rows)

async def query_keyword_chunk_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    query: str,
    candidate_limit: int,
    document_ids: set[str] | None = None,
) -> list[str]:
    if db.get_bind().dialect.name != "postgresql" or (
        document_ids is not None and not document_ids
    ):
        return []
    result = await db.execute(
        _QUERY_KEYWORD_CHUNK_IDS,
        {
            "workspace_id": knowledge_base.workspace_id,
            "knowledge_base_id": knowledge_base.id,
            "query": query,
            "candidate_limit": candidate_limit,
            "document_ids": sorted(document_ids) if document_ids is not None else None,
        },
    )
    return list(result.scalars())

async def list_indexed_chunk_ids_for_parent_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    parent_ids: list[str],
) -> list[str]:
    if not parent_ids:
        return []
    rows = list(
        await db.scalars(
            select(KnowledgeDocumentChunkORM)
            .where(
                KnowledgeDocumentChunkORM.workspace_id
                == knowledge_base.workspace_id,
                KnowledgeDocumentChunkORM.knowledge_base_id
                == knowledge_base.id,
                KnowledgeDocumentChunkORM.status == CHUNK_INDEXED_STATUS,
                KnowledgeDocumentChunkORM.parent_id.in_(parent_ids),
            )
            .order_by(KnowledgeDocumentChunkORM.chunk_index)
        )
    )
    positions = {parent_id: index for index, parent_id in enumerate(parent_ids)}
    return [
        row.id
        for row in sorted(
            rows,
            key=lambda row: (
                positions.get(row.parent_id, len(positions)),
                row.chunk_index,
                row.id,
            ),
        )
    ]

async def delete_document_chunks(db: AsyncSession, document_id: str) -> None:
    await db.execute(
        delete(KnowledgeChunkAssetORM).where(
            KnowledgeChunkAssetORM.document_id == document_id
        )
    )
    await db.execute(
        delete(KnowledgeDocumentChunkORM).where(
            KnowledgeDocumentChunkORM.document_id == document_id
        )
    )
    await db.execute(
        delete(KnowledgeDocumentParentChunkORM).where(
            KnowledgeDocumentParentChunkORM.document_id == document_id
        )
    )

async def get_queued_graph_sync(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.task_type == "graph_sync",
            KnowledgeTaskORM.status == TASK_QUEUED_STATUS,
        )
        .order_by(KnowledgeTaskORM.created_at, KnowledgeTaskORM.id)
    )
    return to_entity(KnowledgeTask, row) if row else None

async def get_queued_graph_rebuild(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.task_type == "graph_rebuild",
            KnowledgeTaskORM.status == TASK_QUEUED_STATUS,
        )
        .order_by(KnowledgeTaskORM.created_at, KnowledgeTaskORM.id)
    )
    return to_entity(KnowledgeTask, row) if row else None

_QUERY_KEYWORD_CHUNK_IDS = text(
    (
        Path(__file__).parent.parent.parent
        / "sql"
        / "knowledge"
        / "query_keyword_chunk_ids.sql"
    ).read_text(encoding="utf-8")
)

