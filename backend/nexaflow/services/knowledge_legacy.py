import asyncio

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.services.audit import record_audit_log
from nexaflow.core.config import Settings
from nexaflow.models.user import User
from nexaflow.models.knowledge import KnowledgeBase, KnowledgeDocument
from nexaflow.services.knowledge_pipeline import delete_chroma_vectors
from nexaflow.services.knowledge_processing import (
    DOCUMENT_PARSED_STATUS,
    TASK_INDEX,
    get_conflicting_open_task,
    get_knowledge_document,
    replace_document_chunks,
)
from nexaflow.schemas.knowledge import KnowledgeDocumentBatchCreateRequest
from nexaflow.services.knowledge import (
    DEFAULT_DOCUMENT_META,
    RESOURCE_TYPE,
    clean_upload_filename,
)


def batch_paragraph_content(payload: KnowledgeDocumentBatchCreateRequest) -> list[str]:
    contents: list[str] = []
    for paragraph in payload.paragraphs:
        if paragraph.problem_list:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Paragraph problem_list is not supported for ordinary document import.",
            )
        title = paragraph.title.strip()
        content = paragraph.content.strip()
        contents.append(f"{title}\n\n{content}" if title else content)
    return contents


async def batch_create_knowledge_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: list[KnowledgeDocumentBatchCreateRequest],
    actor: User,
    settings: Settings,
) -> list[KnowledgeDocument]:
    if not payload:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Document payload is required.",
        )

    documents: list[KnowledgeDocument] = []
    vector_ids: list[str] = []
    source_file_ids: set[str] = set()
    for item in payload:
        if item.source_file_id in source_file_ids:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Duplicate source_file_id.",
            )
        source_file_ids.add(item.source_file_id)

        document = await get_knowledge_document(
            db,
            knowledge_base,
            item.source_file_id,
        )
        if (
            await get_conflicting_open_task(
                db,
                knowledge_base,
                TASK_INDEX,
                document.id,
            )
            is not None
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Knowledge task is already running.",
            )

        chunk_contents = batch_paragraph_content(item)
        vector_ids.extend(
            await replace_document_chunks(
                db,
                knowledge_base,
                document,
                chunk_contents,
            )
        )
        document.filename = clean_upload_filename(item.name)
        document.meta = {
            **DEFAULT_DOCUMENT_META,
            **(document.meta or {}),
            **item.meta,
            "source_file_id": document.id,
            "preview_file_id": item.preview_file_id,
        }
        document.status = DOCUMENT_PARSED_STATUS
        document.last_error = None
        documents.append(document)

    record_audit_log(
        db,
        actor,
        "knowledge_document.batch_create",
        RESOURCE_TYPE,
        knowledge_base.id,
        knowledge_base.name,
        {"knowledge_base_id": knowledge_base.id, "document_count": len(documents)},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    await asyncio.to_thread(
        delete_chroma_vectors,
        settings,
        knowledge_base.id,
        vector_ids,
    )
    return documents
