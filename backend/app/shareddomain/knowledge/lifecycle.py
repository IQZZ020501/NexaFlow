import asyncio

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.shareddomain.audit.services import record_audit_log
from app.infrastructure.config import Settings
from app.entities.user import User
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.entities.knowledge import (
    DOCUMENT_DELETED_STATUS,
    KnowledgeAttachment,
    KnowledgeBase,
    KnowledgeDocument,
)
from app.ports.vector_store import delete_vectors
from app.shareddomain.knowledge.permissions import require_knowledge_base_active
from app.shareddomain.knowledge.references import (
    detach_document_references,
    resolve_references_matching_document,
)
from app.shareddomain.knowledge.services import knowledge_object_storage


async def delete_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: User,
    settings: Settings,
) -> None:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
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
    await detach_document_references(db, knowledge_base, document.id)
    asset_object_keys = await knowledge_base_repository.delete_document_assets(
        db,
        document.id,
    )
    await knowledge_base_repository.delete_document_chunks(db, document.id)
    document.status = DOCUMENT_DELETED_STATUS
    document.last_error = None
    if document.attachment_id:
        attachment = await knowledge_base_repository.get_knowledge_attachment_by_id(
            db,
            document.attachment_id,
        )
        if attachment is not None:
            attachment.status = "deleted"
            await knowledge_base_repository.save_knowledge_attachment(db, attachment)
    await knowledge_base_repository.save_knowledge_document(db, document)
    await resolve_references_matching_document(db, knowledge_base, document)
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
) -> KnowledgeDocument:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
    document = await knowledge_base_repository.get_knowledge_document_by_id(
        db,
        document.id,
    )
    if (
        document is None
        or document.workspace_id != knowledge_base.workspace_id
        or document.knowledge_base_id != knowledge_base.id
        or document.status == DOCUMENT_DELETED_STATUS
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge document not found.")
    if document.is_active == is_active:
        return document

    document.is_active = is_active
    await knowledge_base_repository.save_knowledge_document(db, document)
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
    return document
