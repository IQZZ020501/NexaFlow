"""Queue a whole knowledge-base selection before dispatching any work."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit.services import record_audit_log
from app.domain.knowledge.bases.permissions import (
    require_knowledge_base_active,
    require_knowledge_base_permission,
)
from app.domain.knowledge.tasks.orchestration import (
    MAX_TASK_ATTEMPTS,
    resolve_embedding_model,
)
from app.entities.identity.user import User
from app.entities.knowledge import (
    DOCUMENT_INDEX_FAILED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    DOCUMENT_PARSED_STATUS,
    TASK_EVALUATE,
    TASK_INDEX,
    TASK_REBUILD_INDEX,
    KnowledgeBase,
    KnowledgeTask,
)
from app.infra.db.repositories.knowledge import indexing
from app.infra.db.repositories.knowledge import repository as knowledge_base_repository
from app.schemas.knowledge import KnowledgeDocumentIndexScope


async def enqueue_index_knowledge_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    scope: KnowledgeDocumentIndexScope,
) -> list[str]:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db, knowledge_base
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
    await require_knowledge_base_permission(db, knowledge_base, actor, {"edit"})
    for task_type in (TASK_REBUILD_INDEX, TASK_EVALUATE):
        if await knowledge_base_repository.get_open_knowledge_task(
            db, knowledge_base, task_type, None
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Knowledge task is already running."
            )
    statuses = {DOCUMENT_PARSED_STATUS, DOCUMENT_INDEX_FAILED_STATUS}
    if scope == "all":
        statuses.add(DOCUMENT_INDEXED_STATUS)
    candidates = await indexing.list_batch_index_documents(db, knowledge_base, statuses)
    if not candidates:
        return []
    embedding_model = await resolve_embedding_model(
        db, knowledge_base, user_id=actor.id
    )
    if embedding_model is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Embedding model is required."
        )
    if knowledge_base.embedding_model_id is None:
        await knowledge_base_repository.set_knowledge_base_embedding_model_id(
            db, knowledge_base.id, embedding_model.id
        )
    tasks = [
        KnowledgeTask(
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_id=knowledge_base.id,
            document_id=document_id,
            task_type=TASK_INDEX,
            max_attempts=MAX_TASK_ATTEMPTS,
            total_items=chunk_count,
            created_by_user_id=actor.id,
        )
        for document_id, chunk_count in candidates
    ]
    await indexing.create_batch_index_tasks(db, knowledge_base, tasks)
    record_audit_log(
        db,
        actor,
        "knowledge_document.index.batch",
        "knowledge_base",
        knowledge_base.id,
        knowledge_base.name,
        {"scope": scope, "document_count": len(tasks)},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    return [task.id for task in tasks]
