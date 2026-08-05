import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.shareddomain.audit.services import record_audit_log
from app.infrastructure.config import Settings
from app.domain.user import User
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.shareddomain.knowledge.models import KnowledgeAttachment, KnowledgeBase, KnowledgeDocument
from app.capabilities.rag.vector_store import delete_vectors
from app.shareddomain.knowledge.orchestration import DOCUMENT_DELETED_STATUS
from app.shareddomain.knowledge.services import knowledge_object_storage


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
    asset_object_keys = await knowledge_base_repository.delete_document_assets(
        db,
        document.id,
    )
    await knowledge_base_repository.delete_document_chunks(db, document.id)
    document.status = DOCUMENT_DELETED_STATUS
    document.last_error = None
    if document.attachment_id:
        attachment = await db.get(KnowledgeAttachment, document.attachment_id)
        if attachment is not None:
            attachment.status = "deleted"
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
    storage = knowledge_object_storage(settings)
    storage.delete(document.storage_path)
    for object_key in asset_object_keys:
        storage.delete(object_key)
    await asyncio.to_thread(
        delete_vectors,
        settings,
        knowledge_base.id,
        vector_ids,
    )


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
