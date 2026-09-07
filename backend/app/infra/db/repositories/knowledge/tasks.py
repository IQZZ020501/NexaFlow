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

async def list_recoverable_tasks(
    db: AsyncSession,
    now: datetime,
    *,
    limit: int = 200,
) -> list[KnowledgeTask]:
    result = await db.scalars(
        select(KnowledgeTaskORM)
        .where(
            or_(
                and_(
                    KnowledgeTaskORM.attempts < KnowledgeTaskORM.max_attempts,
                    or_(
                        KnowledgeTaskORM.status == TASK_QUEUED_STATUS,
                        and_(
                            KnowledgeTaskORM.status == TASK_RUNNING_STATUS,
                            or_(
                                KnowledgeTaskORM.lease_expires_at.is_(None),
                                KnowledgeTaskORM.lease_expires_at <= now,
                            ),
                        ),
                    ),
                ),
                and_(
                    KnowledgeTaskORM.status == TASK_CANCELLING_STATUS,
                    or_(
                        KnowledgeTaskORM.lease_expires_at.is_(None),
                        KnowledgeTaskORM.lease_expires_at <= now,
                    ),
                ),
            )
        )
        .order_by(KnowledgeTaskORM.created_at, KnowledgeTaskORM.id)
        .limit(limit)
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

async def delete_knowledge_task(db: AsyncSession, entity: KnowledgeTask) -> None:
    row = await db.get(KnowledgeTaskORM, entity.id)
    if row is not None:
        await db.delete(row)

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
    earlier_graph_task = KnowledgeTaskORM.__table__.alias("earlier_graph_task")
    # ponytail: serialize graph publication per knowledge base; split extraction
    # workers only when measured backlog shows this ceiling is material.
    earlier_graph_task_exists = (
        select(1)
        .select_from(earlier_graph_task)
        .where(
            earlier_graph_task.c.workspace_id == KnowledgeTaskORM.workspace_id,
            earlier_graph_task.c.knowledge_base_id
            == KnowledgeTaskORM.knowledge_base_id,
            earlier_graph_task.c.task_type.in_(["graph_sync", "graph_rebuild"]),
            earlier_graph_task.c.status.in_(
                [TASK_QUEUED_STATUS, TASK_RUNNING_STATUS, TASK_CANCELLING_STATUS]
            ),
            or_(
                earlier_graph_task.c.created_at < KnowledgeTaskORM.created_at,
                and_(
                    earlier_graph_task.c.created_at == KnowledgeTaskORM.created_at,
                    earlier_graph_task.c.id < KnowledgeTaskORM.id,
                ),
            ),
        )
        .exists()
    )
    result = await db.execute(
        update(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.id == task_id,
            KnowledgeTaskORM.attempts < KnowledgeTaskORM.max_attempts,
            or_(
                KnowledgeTaskORM.task_type.not_in(
                    ["graph_sync", "graph_rebuild"]
                ),
                ~earlier_graph_task_exists,
            ),
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

async def get_running_graph_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.task_type.in_(["graph_sync", "graph_rebuild"]),
            KnowledgeTaskORM.status == TASK_RUNNING_STATUS,
        )
        .order_by(KnowledgeTaskORM.created_at, KnowledgeTaskORM.id)
    )
    return to_entity(KnowledgeTask, row) if row else None

async def get_open_graph_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.task_type.in_([TASK_GRAPH_SYNC, TASK_GRAPH_REBUILD]),
            KnowledgeTaskORM.status.in_(
                [TASK_QUEUED_STATUS, TASK_RUNNING_STATUS, TASK_CANCELLING_STATUS]
            ),
        )
        .order_by(KnowledgeTaskORM.created_at.desc(), KnowledgeTaskORM.id.desc())
    )
    return to_entity(KnowledgeTask, row) if row else None

async def get_latest_graph_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.task_type.in_([TASK_GRAPH_SYNC, TASK_GRAPH_REBUILD]),
        )
        .order_by(
            KnowledgeTaskORM.updated_at.desc(),
            KnowledgeTaskORM.created_at.desc(),
            KnowledgeTaskORM.id.desc(),
        )
        .limit(1)
    )
    return to_entity(KnowledgeTask, row) if row else None

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

async def update_owned_knowledge_task_progress(
    db: AsyncSession,
    task_id: str,
    worker_task_id: str,
    total_items: int,
    processed_items: int,
    lease_expires_at: datetime,
) -> bool:
    result = await db.execute(
        update(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.id == task_id,
            KnowledgeTaskORM.status == TASK_RUNNING_STATUS,
            KnowledgeTaskORM.worker_task_id == worker_task_id,
        )
        .values(
            total_items=total_items,
            processed_items=processed_items,
            lease_expires_at=lease_expires_at,
        )
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
            KnowledgeTaskORM.status.in_(
                [TASK_QUEUED_STATUS, TASK_RUNNING_STATUS, TASK_CANCELLING_STATUS]
            ),
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
            KnowledgeTaskORM.status.in_(
                [TASK_QUEUED_STATUS, TASK_RUNNING_STATUS, TASK_CANCELLING_STATUS]
            ),
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
            KnowledgeTaskORM.status.in_(
                [TASK_QUEUED_STATUS, TASK_RUNNING_STATUS, TASK_CANCELLING_STATUS]
            ),
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
            KnowledgeTaskORM.status.in_(
                [TASK_QUEUED_STATUS, TASK_RUNNING_STATUS, TASK_CANCELLING_STATUS]
            ),
        )
        .order_by(KnowledgeTaskORM.created_at.desc())
    )
    for task in tasks:
        task.status = TASK_FAILED_STATUS
        task.last_error = message
        task.lease_expires_at = None
        task.finished_at = utc_now()

