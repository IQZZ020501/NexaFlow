from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.model_utils import new_id, utc_now
from app.domain.user import User
from app.shareddomain.knowledge.models import (
    DOCUMENT_STAGED_META_KEY,
    KnowledgeAsset,
    KnowledgeAttachment,
    KnowledgeBase,
    KnowledgeChunkAsset,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeTask,
)
from app.domain.resource_permission import ResourcePermission
from app.domain.workspace import WorkspaceMembership

VISIBLE_DOCUMENT_STATUSES = (
    "uploaded",
    "parse_queued",
    "parsing",
    "parsed",
    "parse_failed",
    "index_queued",
    "indexing",
    "indexed",
    "index_failed",
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
):
    grant = ResourcePermission
    statement = select(KnowledgeBase, grant).outerjoin(
        grant,
        (
            (grant.workspace_id == KnowledgeBase.workspace_id)
            & (grant.resource_type == resource_type)
            & (grant.resource_id == KnowledgeBase.id)
            & (grant.user_id == actor_id)
        ),
    ).where(KnowledgeBase.workspace_id == workspace_id)

    if workspace_role != "admin":
        statement = statement.where(
            or_(
                KnowledgeBase.created_by_user_id == actor_id,
                grant.id.is_not(None),
            )
        )

    statement = statement.order_by(
        KnowledgeBase.created_at.desc(),
        KnowledgeBase.id.desc(),
    )
    result = await db.execute(statement.limit(limit).offset(offset))
    return result.all()


async def get_knowledge_base_by_id(
    db: AsyncSession,
    knowledge_base_id: str,
) -> KnowledgeBase | None:
    return await db.get(KnowledgeBase, knowledge_base_id)


async def lock_knowledge_base(db: AsyncSession, knowledge_base: KnowledgeBase) -> None:
    await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.id == knowledge_base.id)
        .with_for_update()
    )


async def list_knowledge_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    include_staged: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeDocument]:
    statement = select(KnowledgeDocument).where(
        KnowledgeDocument.workspace_id == knowledge_base.workspace_id,
        KnowledgeDocument.knowledge_base_id == knowledge_base.id,
        KnowledgeDocument.status != "deleted",
    )
    if not include_staged:
        statement = statement.where(
            KnowledgeDocument.status.in_(VISIBLE_DOCUMENT_STATUSES),
            KnowledgeDocument.meta[DOCUMENT_STAGED_META_KEY]
            .as_boolean()
            .is_not(True),
        )
    statement = statement.order_by(
        KnowledgeDocument.created_at.desc(),
        KnowledgeDocument.id.desc(),
    )
    result = await db.scalars(statement.limit(limit).offset(offset))
    return list(result)


async def get_knowledge_document_by_id(
    db: AsyncSession,
    document_id: str,
) -> KnowledgeDocument | None:
    return await db.get(KnowledgeDocument, document_id)


async def get_knowledge_attachment_by_id(
    db: AsyncSession,
    attachment_id: str,
) -> KnowledgeAttachment | None:
    return await db.get(KnowledgeAttachment, attachment_id)


async def lock_knowledge_attachments(
    db: AsyncSession,
    attachment_ids: list[str],
) -> list[KnowledgeAttachment]:
    result = await db.scalars(
        select(KnowledgeAttachment)
        .where(KnowledgeAttachment.id.in_(attachment_ids))
        .with_for_update()
    )
    return list(result)


async def list_document_assets(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
) -> list[KnowledgeAsset]:
    result = await db.scalars(
        select(KnowledgeAsset)
        .where(
            KnowledgeAsset.workspace_id == knowledge_base.workspace_id,
            KnowledgeAsset.knowledge_base_id == knowledge_base.id,
            KnowledgeAsset.document_id == document_id,
        )
        .order_by(KnowledgeAsset.asset_index, KnowledgeAsset.id)
    )
    return list(result)


async def get_document_asset(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
    asset_id: str,
) -> KnowledgeAsset | None:
    return await db.scalar(
        select(KnowledgeAsset).where(
            KnowledgeAsset.workspace_id == knowledge_base.workspace_id,
            KnowledgeAsset.knowledge_base_id == knowledge_base.id,
            KnowledgeAsset.document_id == document_id,
            KnowledgeAsset.id == asset_id,
        )
    )


async def list_chunk_assets(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    chunk_ids: set[str],
) -> list[tuple[KnowledgeChunkAsset, KnowledgeAsset]]:
    if not chunk_ids:
        return []
    result = await db.execute(
        select(KnowledgeChunkAsset, KnowledgeAsset)
        .join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeChunkAsset.asset_id)
        .where(
            KnowledgeChunkAsset.workspace_id == knowledge_base.workspace_id,
            KnowledgeChunkAsset.knowledge_base_id == knowledge_base.id,
            KnowledgeChunkAsset.chunk_id.in_(chunk_ids),
        )
        .order_by(KnowledgeChunkAsset.chunk_id, KnowledgeChunkAsset.asset_index)
    )
    return list(result.all())


async def delete_document_assets(db: AsyncSession, document_id: str) -> list[str]:
    object_keys = list(
        await db.scalars(
            select(KnowledgeAsset.object_key).where(
                KnowledgeAsset.document_id == document_id
            )
        )
    )
    await db.execute(
        delete(KnowledgeChunkAsset).where(
            KnowledgeChunkAsset.document_id == document_id
        )
    )
    await db.execute(delete(KnowledgeAsset).where(KnowledgeAsset.document_id == document_id))
    return object_keys


async def count_document_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> dict[str, int]:
    result = await db.execute(
        select(KnowledgeDocumentChunk.document_id, func.count())
        .where(
            KnowledgeDocumentChunk.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunk.knowledge_base_id == knowledge_base.id,
        )
        .group_by(KnowledgeDocumentChunk.document_id)
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
        select(KnowledgeDocumentChunk)
        .where(
            KnowledgeDocumentChunk.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunk.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentChunk.document_id == document_id,
        )
        .order_by(
            KnowledgeDocumentChunk.chunk_index,
            KnowledgeDocumentChunk.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return list(result)


async def list_indexable_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str | None = None,
    statuses: set[str] | None = None,
) -> list[KnowledgeDocumentChunk]:
    statement = select(KnowledgeDocumentChunk).where(
        KnowledgeDocumentChunk.workspace_id == knowledge_base.workspace_id,
        KnowledgeDocumentChunk.knowledge_base_id == knowledge_base.id,
    )
    if document_id is not None:
        statement = statement.where(KnowledgeDocumentChunk.document_id == document_id)
    if statuses is not None:
        statement = statement.where(KnowledgeDocumentChunk.status.in_(statuses))
    result = await db.scalars(statement.order_by(KnowledgeDocumentChunk.document_id, KnowledgeDocumentChunk.chunk_index))
    return list(result)


async def list_chunks_by_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    chunk_ids: list[str],
) -> list[KnowledgeDocumentChunk]:
    if not chunk_ids:
        return []
    result = await db.scalars(
        select(KnowledgeDocumentChunk).where(
            KnowledgeDocumentChunk.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunk.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentChunk.status == "indexed",
            KnowledgeDocumentChunk.id.in_(chunk_ids),
        )
    )
    return list(result)


async def list_parent_chunks_by_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    parent_ids: set[str],
) -> list[KnowledgeDocumentParentChunk]:
    if not parent_ids:
        return []
    result = await db.scalars(
        select(KnowledgeDocumentParentChunk).where(
            KnowledgeDocumentParentChunk.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentParentChunk.knowledge_base_id == knowledge_base.id,
            KnowledgeDocumentParentChunk.id.in_(parent_ids),
        )
    )
    return list(result)


async def list_active_documents_by_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_ids: set[str],
) -> list[KnowledgeDocument]:
    if not document_ids:
        return []
    result = await db.scalars(
        select(KnowledgeDocument).where(
            KnowledgeDocument.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base.id,
            KnowledgeDocument.id.in_(document_ids),
            KnowledgeDocument.status != "deleted",
            KnowledgeDocument.is_active.is_(True),
        )
    )
    return list(result)


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
        delete(KnowledgeChunkAsset).where(
            KnowledgeChunkAsset.document_id == document_id
        )
    )
    await db.execute(delete(KnowledgeDocumentChunk).where(KnowledgeDocumentChunk.document_id == document_id))
    await db.execute(
        delete(KnowledgeDocumentParentChunk).where(
            KnowledgeDocumentParentChunk.document_id == document_id
        )
    )


async def list_knowledge_tasks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeTask]:
    statement = select(KnowledgeTask).where(
        KnowledgeTask.workspace_id == knowledge_base.workspace_id,
        KnowledgeTask.knowledge_base_id == knowledge_base.id,
    )
    if document_id is not None:
        statement = statement.where(KnowledgeTask.document_id == document_id)
    statement = statement.order_by(
        KnowledgeTask.created_at.desc(),
        KnowledgeTask.id.desc(),
    )
    result = await db.scalars(statement.limit(limit).offset(offset))
    return list(result)


async def list_recoverable_tasks(db: AsyncSession) -> list[KnowledgeTask]:
    result = await db.scalars(
        select(KnowledgeTask)
        .where(KnowledgeTask.status.in_(["queued", "running"]))
        .order_by(KnowledgeTask.created_at)
    )
    return list(result)


async def get_knowledge_task_by_id(db: AsyncSession, task_id: str) -> KnowledgeTask | None:
    return await db.get(KnowledgeTask, task_id)


async def claim_knowledge_task(
    db: AsyncSession,
    task_id: str,
    started_at: datetime,
    lease_expires_at: datetime,
    worker_task_id: str,
) -> bool:
    result = await db.execute(
        update(KnowledgeTask)
        .where(
            KnowledgeTask.id == task_id,
            KnowledgeTask.attempts < KnowledgeTask.max_attempts,
            or_(
                KnowledgeTask.status == "queued",
                (KnowledgeTask.status == "running")
                & or_(
                    KnowledgeTask.lease_expires_at.is_(None),
                    KnowledgeTask.lease_expires_at <= started_at,
                ),
            ),
        )
        .values(
            status="running",
            attempts=KnowledgeTask.attempts + 1,
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
        update(KnowledgeTask)
        .where(
            KnowledgeTask.id == task_id,
            KnowledgeTask.status == "running",
            KnowledgeTask.worker_task_id == worker_task_id,
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
    return await db.scalar(
        select(KnowledgeTask)
        .where(
            KnowledgeTask.workspace_id == knowledge_base.workspace_id,
            KnowledgeTask.knowledge_base_id == knowledge_base.id,
            KnowledgeTask.document_id == document_id,
            KnowledgeTask.task_type == task_type,
            KnowledgeTask.status.in_(["queued", "running"]),
        )
        .order_by(KnowledgeTask.created_at.desc())
    )


async def get_open_knowledge_base_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeTask | None:
    return await db.scalar(
        select(KnowledgeTask)
        .where(
            KnowledgeTask.workspace_id == knowledge_base.workspace_id,
            KnowledgeTask.knowledge_base_id == knowledge_base.id,
            KnowledgeTask.status.in_(["queued", "running"]),
        )
        .order_by(KnowledgeTask.created_at.desc())
    )


async def get_open_document_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
) -> KnowledgeTask | None:
    return await db.scalar(
        select(KnowledgeTask)
        .where(
            KnowledgeTask.workspace_id == knowledge_base.workspace_id,
            KnowledgeTask.knowledge_base_id == knowledge_base.id,
            KnowledgeTask.document_id == document_id,
            KnowledgeTask.status.in_(["queued", "running"]),
        )
        .order_by(KnowledgeTask.created_at.desc())
    )


async def fail_open_document_tasks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
    message: str,
) -> None:
    tasks = await db.scalars(
        select(KnowledgeTask)
        .where(
            KnowledgeTask.workspace_id == knowledge_base.workspace_id,
            KnowledgeTask.knowledge_base_id == knowledge_base.id,
            KnowledgeTask.document_id == document_id,
            KnowledgeTask.status.in_(["queued", "running"]),
        )
        .order_by(KnowledgeTask.created_at.desc())
    )
    for task in tasks:
        task.status = "failed"
        task.last_error = message
        task.lease_expires_at = None
        task.finished_at = utc_now()


async def get_user_grant(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    user_id: str,
    resource_type: str,
) -> ResourcePermission | None:
    return await db.scalar(
        select(ResourcePermission).where(
            ResourcePermission.workspace_id == knowledge_base.workspace_id,
            ResourcePermission.resource_type == resource_type,
            ResourcePermission.resource_id == knowledge_base.id,
            ResourcePermission.user_id == user_id,
        )
    )


async def list_resource_permission_rows(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    resource_type: str,
    limit: int | None = None,
    offset: int = 0,
):
    result = await db.execute(
        select(ResourcePermission, User)
        .join(User, User.id == ResourcePermission.user_id)
        .where(
            ResourcePermission.workspace_id == knowledge_base.workspace_id,
            ResourcePermission.resource_type == resource_type,
            ResourcePermission.resource_id == knowledge_base.id,
        )
        .order_by(User.name, User.id)
        .limit(limit)
        .offset(offset)
    )
    return result.all()


async def get_active_workspace_member(
    db: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> User | None:
    return await db.scalar(
        select(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
            User.is_active.is_(True),
        )
    )


async def delete_knowledge_base_graph(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    resource_type: str,
) -> None:
    await db.execute(
        delete(KnowledgeTask).where(
            KnowledgeTask.workspace_id == knowledge_base.workspace_id,
            KnowledgeTask.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeChunkAsset).where(
            KnowledgeChunkAsset.workspace_id == knowledge_base.workspace_id,
            KnowledgeChunkAsset.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeDocumentChunk).where(
            KnowledgeDocumentChunk.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentChunk.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeDocumentParentChunk).where(
            KnowledgeDocumentParentChunk.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocumentParentChunk.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeAsset).where(
            KnowledgeAsset.workspace_id == knowledge_base.workspace_id,
            KnowledgeAsset.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeDocument).where(
            KnowledgeDocument.workspace_id == knowledge_base.workspace_id,
            KnowledgeDocument.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(KnowledgeAttachment).where(
            KnowledgeAttachment.workspace_id == knowledge_base.workspace_id,
            KnowledgeAttachment.knowledge_base_id == knowledge_base.id,
        )
    )
    await db.execute(
        delete(ResourcePermission).where(
            ResourcePermission.workspace_id == knowledge_base.workspace_id,
            ResourcePermission.resource_type == resource_type,
            ResourcePermission.resource_id == knowledge_base.id,
        )
    )
    await db.execute(delete(KnowledgeBase).where(KnowledgeBase.id == knowledge_base.id))


async def delete_resource_permission(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_user_id: str,
    resource_type: str,
) -> int:
    result = await db.execute(
        delete(ResourcePermission).where(
            ResourcePermission.workspace_id == knowledge_base.workspace_id,
            ResourcePermission.resource_type == resource_type,
            ResourcePermission.resource_id == knowledge_base.id,
            ResourcePermission.user_id == target_user_id,
        )
    )
    return result.rowcount
