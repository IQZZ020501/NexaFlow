"""Knowledge documents and attachments."""

from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    DOCUMENT_STAGED_META_KEY,
    KnowledgeAttachment,
    KnowledgeBase,
    KnowledgeDocument,
)
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import new_id
from app.infrastructure.object_storage import (
    EmptyObjectError,
    ObjectStorage,
    ObjectTooLargeError,
    create_object_storage,
)
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.schemas.knowledge import (
    KnowledgeAttachmentResponse,
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentResponse,
)
from app.shareddomain.audit.services import record_audit_log

DOCUMENT_UPLOADED_STATUS = "uploaded"
MAX_DOCUMENT_UPLOAD_BYTES = 100 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
DEFAULT_DOCUMENT_META = {
    "allow_download": True,
    "security_level": "PUBLIC",
    DOCUMENT_STAGED_META_KEY: False,
}
RESTRICTED_FILENAME_MARKERS = ("秘密", "机密", "绝密")


def attachment_to_response(attachment: KnowledgeAttachment) -> KnowledgeAttachmentResponse:
    return KnowledgeAttachmentResponse(
        id=attachment.id,
        workspace_id=attachment.workspace_id,
        knowledge_base_id=attachment.knowledge_base_id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        status=attachment.status,
        created_by_user_id=attachment.created_by_user_id,
        created_at=attachment.created_at,
        updated_at=attachment.updated_at,
    )


def document_to_response(
    document: KnowledgeDocument,
    chunk_count: int = 0,
) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse(
        id=document.id,
        workspace_id=document.workspace_id,
        knowledge_base_id=document.knowledge_base_id,
        filename=document.filename,
        content_type=document.content_type,
        attachment_id=document.attachment_id,
        size_bytes=document.size_bytes,
        meta=document.meta,
        status=document.status,
        is_active=document.is_active,
        chunk_count=chunk_count,
        last_error=document.last_error,
        created_by_user_id=document.created_by_user_id,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def clean_upload_filename(filename: str | None) -> str:
    name = Path(filename or "").name.strip()
    if not name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Document filename is required.",
        )
    if any(marker in name for marker in RESTRICTED_FILENAME_MARKERS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Document filename contains restricted classification.",
        )
    return name[:255]


def knowledge_object_storage(settings: Settings) -> ObjectStorage:
    return create_object_storage(settings.knowledge_storage_dir)


def knowledge_document_path(settings: Settings, storage_path: str) -> Path:
    return knowledge_object_storage(settings).path(storage_path)


async def list_knowledge_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    include_staged: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeDocumentResponse]:
    return [
        document_to_response(document)
        for document in await knowledge_base_repository.list_knowledge_documents(
            db,
            knowledge_base,
            include_staged=include_staged,
            limit=limit,
            offset=offset,
        )
    ]


async def upload_knowledge_attachment(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    upload: UploadFile,
    actor: User,
    settings: Settings,
) -> KnowledgeAttachmentResponse:
    attachment_id = new_id()
    filename = clean_upload_filename(upload.filename)
    object_key = (
        f"{knowledge_base.workspace_id}/{knowledge_base.id}/attachments/"
        f"{attachment_id}/{filename}"
    )
    storage = knowledge_object_storage(settings)

    async def chunks():
        while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
            yield chunk

    try:
        size = await storage.put_chunks(
            object_key,
            chunks(),
            MAX_DOCUMENT_UPLOAD_BYTES,
        )
    except ObjectTooLargeError as exc:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Document is too large.",
        ) from exc
    except EmptyObjectError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Document is empty.") from exc

    attachment = KnowledgeAttachment(
        id=attachment_id,
        workspace_id=knowledge_base.workspace_id,
        knowledge_base_id=knowledge_base.id,
        filename=filename,
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=size,
        object_key=object_key,
        status="available",
        created_by_user_id=actor.id,
    )
    attachment = await knowledge_base_repository.create_knowledge_attachment(
        db,
        attachment,
    )
    record_audit_log(
        db,
        actor,
        "knowledge_attachment.upload",
        "knowledge_attachment",
        attachment.id,
        attachment.filename,
        {
            "workspace_id": knowledge_base.workspace_id,
            "knowledge_base_id": knowledge_base.id,
            "size_bytes": size,
        },
        workspace_id=knowledge_base.workspace_id,
    )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        storage.delete(object_key)
        raise
    attachment = await knowledge_base_repository.refresh_knowledge_attachment(
        db,
        attachment,
    )
    return attachment_to_response(attachment)


async def delete_knowledge_attachment(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    attachment_id: str,
    actor: User,
    settings: Settings,
) -> None:
    attachment = await knowledge_base_repository.get_knowledge_attachment_by_id(
        db,
        attachment_id,
    )
    if (
        attachment is None
        or attachment.workspace_id != knowledge_base.workspace_id
        or attachment.knowledge_base_id != knowledge_base.id
        or attachment.created_by_user_id != actor.id
        or attachment.status != "available"
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge attachment not found.")
    object_key = attachment.object_key
    await knowledge_base_repository.delete_knowledge_attachment(db, attachment)
    await db.commit()
    knowledge_object_storage(settings).delete(object_key)


async def create_knowledge_documents_from_attachments(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeDocumentCreateRequest,
    actor: User,
) -> list[KnowledgeDocumentResponse]:
    attachment_ids = list(dict.fromkeys(payload.attachment_ids))
    if len(attachment_ids) != len(payload.attachment_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Duplicate attachment id.",
        )
    attachments = await knowledge_base_repository.lock_knowledge_attachments(
        db,
        attachment_ids,
    )
    attachments_by_id = {attachment.id: attachment for attachment in attachments}
    if set(attachments_by_id) != set(attachment_ids):
        await db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge attachment not found.")

    documents: list[KnowledgeDocument] = []
    for attachment_id in attachment_ids:
        attachment = attachments_by_id[attachment_id]
        if (
            attachment.workspace_id != knowledge_base.workspace_id
            or attachment.knowledge_base_id != knowledge_base.id
            or attachment.created_by_user_id != actor.id
            or attachment.status != "available"
        ):
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Knowledge attachment is unavailable.",
            )
        document = KnowledgeDocument(
            id=new_id(),
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_id=knowledge_base.id,
            attachment_id=attachment.id,
            filename=attachment.filename,
            content_type=attachment.content_type,
            size_bytes=attachment.size_bytes,
            storage_path=attachment.object_key,
            meta={
                **DEFAULT_DOCUMENT_META,
                DOCUMENT_STAGED_META_KEY: payload.staged,
                "import_mode": payload.import_mode,
            },
            status=DOCUMENT_UPLOADED_STATUS,
            last_error=None,
            created_by_user_id=actor.id,
        )
        attachment.status = "consumed"
        documents.append(
            await knowledge_base_repository.create_knowledge_document(db, document)
        )
        await knowledge_base_repository.save_knowledge_attachment(db, attachment)

    record_audit_log(
        db,
        actor,
        "knowledge_document.create_from_attachments",
        "knowledge_base",
        knowledge_base.id,
        knowledge_base.name,
        {
            "knowledge_base_id": knowledge_base.id,
            "document_count": len(documents),
        },
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    refreshed = [
        await knowledge_base_repository.refresh_knowledge_document(db, document)
        for document in documents
    ]
    return [document_to_response(document) for document in refreshed]
