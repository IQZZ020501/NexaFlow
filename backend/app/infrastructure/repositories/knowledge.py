from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    CHUNK_INDEXED_STATUS,
    DOCUMENT_DELETED_STATUS,
    DOCUMENT_STAGED_META_KEY,
    TASK_FAILED_STATUS,
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
    KnowledgeTask,
)
from app.entities.resource_permission import ResourcePermission
from app.entities.user import User as UserEntity
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories.mapping import (
    refresh_entity,
    save,
    to_entity,
    to_orm,
)
from app.domain.resource_permission import ResourcePermission as ResourcePermissionORM
from app.domain.user import User as UserORM
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipORM
from app.shareddomain.knowledge.models import (
    KnowledgeAsset as KnowledgeAssetORM,
    KnowledgeAttachment as KnowledgeAttachmentORM,
    KnowledgeBase as KnowledgeBaseORM,
    KnowledgeChunkAsset as KnowledgeChunkAssetORM,
    KnowledgeDocument as KnowledgeDocumentORM,
    KnowledgeDocumentChunk as KnowledgeDocumentChunkORM,
    KnowledgeDocumentParentChunk as KnowledgeDocumentParentChunkORM,
    KnowledgeTask as KnowledgeTaskORM,
)

_QUERY_KEYWORD_CHUNK_IDS = text(
    (
        Path(__file__).parents[1]
        / "sql"
        / "knowledge"
        / "query_keyword_chunk_ids.sql"
    ).read_text(encoding="utf-8")
)


async def list_knowledge_base_rows(
    db: AsyncSession,
    workspace_id: str,
    actor_id: str,
    workspace_role: str | None,
    resource_type: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[tuple[KnowledgeBase, ResourcePermission | None]]:
    grant = ResourcePermissionORM
    statement = select(KnowledgeBaseORM, grant).outerjoin(
        grant,
        (
            (grant.workspace_id == KnowledgeBaseORM.workspace_id)
            & (grant.resource_type == resource_type)
            & (grant.resource_id == KnowledgeBaseORM.id)
            & (grant.user_id == actor_id)
        ),
    ).where(KnowledgeBaseORM.workspace_id == workspace_id)

    if workspace_role != "admin":
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
        )
        for knowledge_base, permission in result.all()
    ]


async def get_knowledge_base_by_id(
    db: AsyncSession,
    knowledge_base_id: str,
) -> KnowledgeBase | None:
    row = await db.get(KnowledgeBaseORM, knowledge_base_id)
    return to_entity(KnowledgeBase, row) if row else None


async def lock_knowledge_base(db: AsyncSession, knowledge_base: KnowledgeBase) -> None:
    await db.execute(
        select(KnowledgeBaseORM)
        .where(KnowledgeBaseORM.id == knowledge_base.id)
        .with_for_update()
    )


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


async def refresh_knowledge_base(
    db: AsyncSession,
    entity: KnowledgeBase,
) -> KnowledgeBase:
    return await refresh_entity(db, KnowledgeBaseORM, KnowledgeBase, entity)


async def delete_knowledge_base(db: AsyncSession, entity: KnowledgeBase) -> None:
    row = await db.get(KnowledgeBaseORM, entity.id)
    if row is not None:
        await db.delete(row)


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
        statement = statement.where(
            KnowledgeDocumentORM.status.in_(VISIBLE_DOCUMENT_STATUSES),
            KnowledgeDocumentORM.meta[DOCUMENT_STAGED_META_KEY]
            .as_boolean()
            .is_not(True),
        )
    statement = statement.order_by(
        KnowledgeDocumentORM.created_at.desc(),
        KnowledgeDocumentORM.id.desc(),
    )
    result = await db.scalars(statement.limit(limit).offset(offset))
    return [to_entity(KnowledgeDocument, row) for row in result]


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


async def query_keyword_chunk_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    query: str,
    candidate_limit: int,
) -> list[str]:
    if db.get_bind().dialect.name != "postgresql":
        return []
    result = await db.execute(
        _QUERY_KEYWORD_CHUNK_IDS,
        {
            "workspace_id": knowledge_base.workspace_id,
            "knowledge_base_id": knowledge_base.id,
            "query": query,
            "candidate_limit": candidate_limit,
        },
    )
    return list(result.scalars())


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


async def list_knowledge_tasks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeTask]:
    statement = select(KnowledgeTaskORM).where(
        KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
        KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
    )
    if document_id is not None:
        statement = statement.where(KnowledgeTaskORM.document_id == document_id)
    statement = statement.order_by(
        KnowledgeTaskORM.created_at.desc(),
        KnowledgeTaskORM.id.desc(),
    )
    result = await db.scalars(statement.limit(limit).offset(offset))
    return [to_entity(KnowledgeTask, row) for row in result]


async def list_recoverable_tasks(db: AsyncSession) -> list[KnowledgeTask]:
    result = await db.scalars(
        select(KnowledgeTaskORM)
        .where(KnowledgeTaskORM.status.in_([TASK_QUEUED_STATUS, TASK_RUNNING_STATUS]))
        .order_by(KnowledgeTaskORM.created_at)
    )
    return [to_entity(KnowledgeTask, row) for row in result]


async def get_knowledge_task_by_id(
    db: AsyncSession,
    task_id: str,
) -> KnowledgeTask | None:
    row = await db.get(KnowledgeTaskORM, task_id)
    return to_entity(KnowledgeTask, row) if row else None


async def lock_knowledge_task(
    db: AsyncSession,
    task_id: str,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(KnowledgeTaskORM.id == task_id)
        .with_for_update()
    )
    return to_entity(KnowledgeTask, row) if row else None


async def create_knowledge_task(
    db: AsyncSession,
    entity: KnowledgeTask,
) -> KnowledgeTask:
    row = await save(db, KnowledgeTaskORM, entity)
    return to_entity(KnowledgeTask, row)


async def save_knowledge_task(db: AsyncSession, entity: KnowledgeTask) -> None:
    await save(db, KnowledgeTaskORM, entity)


async def refresh_knowledge_task(
    db: AsyncSession,
    entity: KnowledgeTask,
) -> KnowledgeTask:
    return await refresh_entity(db, KnowledgeTaskORM, KnowledgeTask, entity)


async def claim_knowledge_task(
    db: AsyncSession,
    task_id: str,
    started_at: datetime,
    lease_expires_at: datetime,
    worker_task_id: str,
) -> bool:
    result = await db.execute(
        update(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.id == task_id,
            KnowledgeTaskORM.attempts < KnowledgeTaskORM.max_attempts,
            or_(
                KnowledgeTaskORM.status == TASK_QUEUED_STATUS,
                (KnowledgeTaskORM.status == TASK_RUNNING_STATUS)
                & or_(
                    KnowledgeTaskORM.lease_expires_at.is_(None),
                    KnowledgeTaskORM.lease_expires_at <= started_at,
                ),
            ),
        )
        .values(
            status=TASK_RUNNING_STATUS,
            attempts=KnowledgeTaskORM.attempts + 1,
            started_at=started_at,
            lease_expires_at=lease_expires_at,
            worker_task_id=worker_task_id,
            finished_at=None,
            last_error=None,
        )
    )
    return result.rowcount == 1


async def renew_knowledge_task_lease(
    db: AsyncSession,
    task_id: str,
    worker_task_id: str,
    lease_expires_at: datetime,
) -> bool:
    result = await db.execute(
        update(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.id == task_id,
            KnowledgeTaskORM.status == TASK_RUNNING_STATUS,
            KnowledgeTaskORM.worker_task_id == worker_task_id,
        )
        .values(lease_expires_at=lease_expires_at)
    )
    return result.rowcount == 1


async def get_open_knowledge_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_type: str,
    document_id: str | None,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.document_id == document_id,
            KnowledgeTaskORM.task_type == task_type,
            KnowledgeTaskORM.status.in_([TASK_QUEUED_STATUS, TASK_RUNNING_STATUS]),
        )
        .order_by(KnowledgeTaskORM.created_at.desc())
    )
    return to_entity(KnowledgeTask, row) if row else None


async def get_open_knowledge_base_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.status.in_([TASK_QUEUED_STATUS, TASK_RUNNING_STATUS]),
        )
        .order_by(KnowledgeTaskORM.created_at.desc())
    )
    return to_entity(KnowledgeTask, row) if row else None


async def get_open_document_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.document_id == document_id,
            KnowledgeTaskORM.status.in_([TASK_QUEUED_STATUS, TASK_RUNNING_STATUS]),
        )
        .order_by(KnowledgeTaskORM.created_at.desc())
    )
    return to_entity(KnowledgeTask, row) if row else None


async def fail_open_document_tasks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
    message: str,
) -> None:
    tasks = await db.scalars(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.document_id == document_id,
            KnowledgeTaskORM.status.in_([TASK_QUEUED_STATUS, TASK_RUNNING_STATUS]),
        )
        .order_by(KnowledgeTaskORM.created_at.desc())
    )
    for task in tasks:
        task.status = TASK_FAILED_STATUS
        task.last_error = message
        task.lease_expires_at = None
        task.finished_at = utc_now()


async def get_user_grant(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    user_id: str,
    resource_type: str,
) -> ResourcePermission | None:
    row = await db.scalar(
        select(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == knowledge_base.workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == knowledge_base.id,
            ResourcePermissionORM.user_id == user_id,
        )
    )
    return to_entity(ResourcePermission, row) if row else None


async def create_resource_permission(
    db: AsyncSession,
    entity: ResourcePermission,
) -> ResourcePermission:
    row = await save(db, ResourcePermissionORM, entity)
    return to_entity(ResourcePermission, row)


async def save_resource_permission(
    db: AsyncSession,
    entity: ResourcePermission,
) -> None:
    await save(db, ResourcePermissionORM, entity)


async def list_resource_permission_rows(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    resource_type: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[tuple[ResourcePermission, UserEntity]]:
    result = await db.execute(
        select(ResourcePermissionORM, UserORM)
        .join(UserORM, UserORM.id == ResourcePermissionORM.user_id)
        .where(
            ResourcePermissionORM.workspace_id == knowledge_base.workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == knowledge_base.id,
        )
        .order_by(UserORM.name, UserORM.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        (
            to_entity(ResourcePermission, permission),
            to_entity(UserEntity, user),
        )
        for permission, user in result.all()
    ]


async def get_active_workspace_member(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> UserEntity | None:
    row = await db.scalar(
        select(UserORM)
        .join(
            WorkspaceMembershipORM,
            WorkspaceMembershipORM.user_id == UserORM.id,
        )
        .where(
            WorkspaceMembershipORM.workspace_id == workspace_id,
            WorkspaceMembershipORM.user_id == user_id,
            UserORM.is_active.is_(True),
        )
    )
    return to_entity(UserEntity, row) if row else None


async def delete_knowledge_base_graph(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    resource_type: str,
) -> None:
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


async def delete_resource_permission(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_user_id: str,
    resource_type: str,
) -> int:
    result = await db.execute(
        delete(ResourcePermissionORM).where(
            ResourcePermissionORM.workspace_id == knowledge_base.workspace_id,
            ResourcePermissionORM.resource_type == resource_type,
            ResourcePermissionORM.resource_id == knowledge_base.id,
            ResourcePermissionORM.user_id == target_user_id,
        )
    )
    return result.rowcount
