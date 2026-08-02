import asyncio
import shutil

from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.audit.services import record_audit_log
from nexaflow.core.config import Settings
from nexaflow.identity.models import User
from nexaflow.knowledge import repositories as knowledge_base_repository
from nexaflow.knowledge.models import KnowledgeBase, KnowledgeDocument
from nexaflow.knowledge.pipeline import delete_chroma_vectors
from nexaflow.knowledge.processing import DOCUMENT_DELETED_STATUS
from nexaflow.knowledge.services import knowledge_document_path


async def delete_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: User,
    settings: Settings,
) -> None:
    await knowledge_base_repository.lock_knowledge_base(db, knowledge_base)
    await knowledge_base_repository.fail_open_document_tasks(
        db,
        knowledge_base,
        document.id,
        "Document deleted before task completed.",
    )

    chunks = await knowledge_base_repository.list_document_chunks(
        db,
        knowledge_base,
        document.id,
    )
    vector_ids = [chunk.vector_id for chunk in chunks if chunk.vector_id]
    await knowledge_base_repository.delete_document_chunks(db, document.id)

    document.status = DOCUMENT_DELETED_STATUS
    document.last_error = None
    record_audit_log(
        db,
        actor,
        "knowledge_document.delete",
        "knowledge_document",
        document.id,
        document.filename,
        {"knowledge_base_id": knowledge_base.id},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    await asyncio.to_thread(
        delete_chroma_vectors,
        settings,
        knowledge_base.id,
        vector_ids,
    )

    document_path = knowledge_document_path(settings, document.storage_path)
    shutil.rmtree(document_path.parent, ignore_errors=True)


async def set_knowledge_document_active(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: User,
    is_active: bool,
) -> None:
    if document.is_active == is_active:
        return

    document.is_active = is_active
    record_audit_log(
        db,
        actor,
        "knowledge_document.activate" if is_active else "knowledge_document.deactivate",
        "knowledge_document",
        document.id,
        document.filename,
        {"knowledge_base_id": knowledge_base.id},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
