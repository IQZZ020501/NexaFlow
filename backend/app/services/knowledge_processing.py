import asyncio
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit import record_audit_log
from app.core.config import Settings
from app.core.model_utils import new_id
from app.models.user import User
from app.services import knowledge_repositories as knowledge_base_repository
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeTask,
)
from app.services.knowledge_pipeline import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    KnowledgePipelineError,
    SPLIT_SEPARATORS,
    chunk_token_count,
    clean_text,
    delete_chroma_vectors,
    extract_text,
    split_text,
)
from app.schemas.knowledge import (
    KnowledgeDocumentChunkResponse,
    KnowledgeDocumentParseRequest,
    KnowledgeTaskResponse,
)
from app.services.knowledge import (
    get_knowledge_model,
    knowledge_document_path,
)
from app.models.model import RegisteredModel

DOCUMENT_PARSE_QUEUED_STATUS = "parse_queued"
DOCUMENT_PARSING_STATUS = "parsing"
DOCUMENT_PARSED_STATUS = "parsed"
DOCUMENT_PARSE_FAILED_STATUS = "parse_failed"
DOCUMENT_INDEX_QUEUED_STATUS = "index_queued"
DOCUMENT_INDEXING_STATUS = "indexing"
DOCUMENT_INDEXED_STATUS = "indexed"
DOCUMENT_INDEX_FAILED_STATUS = "index_failed"
DOCUMENT_DELETED_STATUS = "deleted"
CHUNK_PREVIEW_STATUS = "preview"
CHUNK_INDEXED_STATUS = "indexed"
CHUNK_INDEX_FAILED_STATUS = "index_failed"
TASK_PARSE = "parse"
TASK_INDEX = "index"
TASK_REBUILD_INDEX = "rebuild_index"
TASK_QUEUED_STATUS = "queued"
TASK_SUCCEEDED_STATUS = "succeeded"
TASK_FAILED_STATUS = "failed"
MAX_TASK_ATTEMPTS = 3
ALLOWED_CLEANING_RULES = {"trim_lines", "collapse_spaces", "remove_empty_lines"}
DEFAULT_PARSE_OPTIONS: dict[str, Any] = {
    "chunk_size": CHUNK_SIZE,
    "chunk_overlap": CHUNK_OVERLAP,
    "split_separator": "\n\n",
    "cleaning_rules": [],
    "auto_index": True,
}


def chunk_to_response(chunk: KnowledgeDocumentChunk) -> KnowledgeDocumentChunkResponse:
    return KnowledgeDocumentChunkResponse(
        id=chunk.id,
        workspace_id=chunk.workspace_id,
        knowledge_base_id=chunk.knowledge_base_id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        char_count=chunk.char_count,
        token_count=chunk.token_count,
        vector_id=chunk.vector_id,
        status=chunk.status,
        created_at=chunk.created_at,
        updated_at=chunk.updated_at,
    )


def task_to_response(task: KnowledgeTask) -> KnowledgeTaskResponse:
    return KnowledgeTaskResponse(
        id=task.id,
        workspace_id=task.workspace_id,
        knowledge_base_id=task.knowledge_base_id,
        document_id=task.document_id,
        task_type=task.task_type,
        status=task.status,
        attempts=task.attempts,
        max_attempts=task.max_attempts,
        total_items=task.total_items,
        processed_items=task.processed_items,
        last_error=task.last_error,
        created_by_user_id=task.created_by_user_id,
        started_at=task.started_at,
        finished_at=task.finished_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


async def get_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
) -> KnowledgeDocument:
    document = await knowledge_base_repository.get_knowledge_document_by_id(db, document_id)
    if (
        document is None
        or document.workspace_id != knowledge_base.workspace_id
        or document.knowledge_base_id != knowledge_base.id
        or document.status == DOCUMENT_DELETED_STATUS
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge document not found.")
    return document


async def list_knowledge_document_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
) -> list[KnowledgeDocumentChunkResponse]:
    chunks = await knowledge_base_repository.list_document_chunks(db, knowledge_base, document.id)
    return [chunk_to_response(chunk) for chunk in chunks]


async def list_knowledge_tasks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument | None = None,
) -> list[KnowledgeTaskResponse]:
    tasks = await knowledge_base_repository.list_knowledge_tasks(
        db,
        knowledge_base,
        document.id if document else None,
    )
    return [task_to_response(task) for task in tasks]


def task_error_message(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    message = detail if isinstance(detail, str) else str(exc)
    return (message or exc.__class__.__name__)[:2000]


def parse_task_options(payload: KnowledgeDocumentParseRequest | None = None) -> dict[str, Any]:
    options = {**DEFAULT_PARSE_OPTIONS, **(payload.model_dump() if payload else {})}
    if options["chunk_overlap"] >= options["chunk_size"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Chunk overlap must be smaller than chunk size.")
    if options["split_separator"] not in SPLIT_SEPARATORS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported split separator.")

    cleaning_rules = list(dict.fromkeys(options["cleaning_rules"]))
    unknown_rules = set(cleaning_rules) - ALLOWED_CLEANING_RULES
    if unknown_rules:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported cleaning rule.")

    options["cleaning_rules"] = cleaning_rules
    return options


def parse_task_options_from_task(task: KnowledgeTask) -> dict[str, Any]:
    return parse_task_options(KnowledgeDocumentParseRequest(**{**DEFAULT_PARSE_OPTIONS, **task.options}))


async def resolve_embedding_model(db: AsyncSession, knowledge_base: KnowledgeBase) -> RegisteredModel | None:
    embedding_model = await get_knowledge_model(
        db,
        knowledge_base.workspace_id,
        knowledge_base.embedding_model_id,
        "EMBEDDING",
        use_default=True,
    )
    if embedding_model is not None and knowledge_base.embedding_model_id is None:
        knowledge_base.embedding_model_id = embedding_model.id
    return embedding_model


async def extract_document_chunk_contents(
    document: KnowledgeDocument,
    settings: Settings,
    options: dict[str, Any],
) -> list[str]:
    text = await asyncio.to_thread(extract_text, document, knowledge_document_path(settings, document.storage_path))
    text = clean_text(
        text,
        options["cleaning_rules"],
        preserve_empty_lines=options["split_separator"] == "\n\n",
    )
    chunks = split_text(
        text,
        options["chunk_size"],
        options["chunk_overlap"],
        options["split_separator"],
    )
    if not chunks:
        raise KnowledgePipelineError("Document has no extractable chunks.")
    return chunks


async def replace_document_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    chunk_contents: list[str],
) -> list[str]:
    existing_chunks = await knowledge_base_repository.list_document_chunks(db, knowledge_base, document.id)
    vector_ids = [chunk.vector_id for chunk in existing_chunks if chunk.vector_id]
    await knowledge_base_repository.delete_document_chunks(db, document.id)

    for index, content in enumerate(chunk_contents):
        db.add(
            KnowledgeDocumentChunk(
                workspace_id=document.workspace_id,
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                chunk_index=index,
                content=content,
                char_count=len(content),
                token_count=chunk_token_count(content),
                status=CHUNK_PREVIEW_STATUS,
            )
        )
    return vector_ids


async def create_knowledge_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument | None,
    task_type: str,
    actor: User,
    options: dict[str, Any] | None = None,
) -> KnowledgeTaskResponse:
    await knowledge_base_repository.lock_knowledge_base(db, knowledge_base)
    document_id = document.id if document else None
    if await get_conflicting_open_task(db, knowledge_base, task_type, document_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge task is already running.")

    total_items = 0
    if task_type == TASK_INDEX and document is not None:
        chunks = await knowledge_base_repository.list_document_chunks(db, knowledge_base, document.id)
        if not chunks:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Document has no preview chunks.")
        total_items = len(chunks)
        document.status = DOCUMENT_INDEX_QUEUED_STATUS
        document.last_error = None
    elif task_type == TASK_PARSE and document is not None:
        document.status = DOCUMENT_PARSE_QUEUED_STATUS
        document.last_error = None
    elif task_type == TASK_REBUILD_INDEX:
        chunks = await knowledge_base_repository.list_indexable_chunks(db, knowledge_base, statuses={CHUNK_INDEXED_STATUS})
        if not chunks:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Knowledge base has no indexed chunks.")
        total_items = len(chunks)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid knowledge task.")

    task = KnowledgeTask(
        id=new_id(),
        workspace_id=knowledge_base.workspace_id,
        knowledge_base_id=knowledge_base.id,
        document_id=document_id,
        task_type=task_type,
        status=TASK_QUEUED_STATUS,
        attempts=0,
        max_attempts=MAX_TASK_ATTEMPTS,
        total_items=total_items,
        processed_items=0,
        options=options or {},
        created_by_user_id=actor.id,
    )
    db.add(task)
    record_audit_log(
        db,
        actor,
        f"knowledge_task.{task_type}.queue",
        "knowledge_task",
        task.id,
        task_type,
        {"knowledge_base_id": knowledge_base.id, "document_id": document_id},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    await db.refresh(task)
    return task_to_response(task)


async def get_conflicting_open_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_type: str,
    document_id: str | None,
) -> KnowledgeTask | None:
    if task_type == TASK_REBUILD_INDEX:
        return await knowledge_base_repository.get_open_knowledge_base_task(db, knowledge_base)
    if document_id is None:
        return await knowledge_base_repository.get_open_knowledge_task(
            db,
            knowledge_base,
            task_type,
            document_id,
        )
    open_task = await knowledge_base_repository.get_open_document_task(
        db,
        knowledge_base,
        document_id,
    )
    if open_task is not None:
        return open_task
    return await knowledge_base_repository.get_open_knowledge_task(
        db,
        knowledge_base,
        TASK_REBUILD_INDEX,
        None,
    )


async def enqueue_parse_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: User,
    payload: KnowledgeDocumentParseRequest | None = None,
) -> KnowledgeTaskResponse:
    return await create_knowledge_task(
        db,
        knowledge_base,
        document,
        TASK_PARSE,
        actor,
        parse_task_options(payload),
    )


async def enqueue_index_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: User,
) -> KnowledgeTaskResponse:
    if document.status not in {
        DOCUMENT_PARSED_STATUS,
        DOCUMENT_INDEXED_STATUS,
        DOCUMENT_INDEX_FAILED_STATUS,
    }:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Document preview must be generated before indexing.",
        )
    if await resolve_embedding_model(db, knowledge_base) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Embedding model is required.")
    return await create_knowledge_task(db, knowledge_base, document, TASK_INDEX, actor)


async def enqueue_rebuild_knowledge_index(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
) -> KnowledgeTaskResponse:
    if await resolve_embedding_model(db, knowledge_base) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Embedding model is required.")
    return await create_knowledge_task(db, knowledge_base, None, TASK_REBUILD_INDEX, actor)


async def retry_knowledge_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
    actor: User,
) -> KnowledgeTaskResponse:
    await knowledge_base_repository.lock_knowledge_base(db, knowledge_base)
    task = await knowledge_base_repository.get_knowledge_task_by_id(db, task_id)
    if task is None or task.workspace_id != knowledge_base.workspace_id or task.knowledge_base_id != knowledge_base.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge task not found.")
    if task.status != TASK_FAILED_STATUS:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed knowledge tasks can be retried.")
    if task.attempts >= task.max_attempts:
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge task retry limit reached.")
    if await get_conflicting_open_task(db, knowledge_base, task.task_type, task.document_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge task is already running.")

    if task.document_id is not None:
        document = await get_knowledge_document(db, knowledge_base, task.document_id)
        if task.task_type == TASK_PARSE:
            document.status = DOCUMENT_PARSE_QUEUED_STATUS
        elif task.task_type == TASK_INDEX:
            document.status = DOCUMENT_INDEX_QUEUED_STATUS
        document.last_error = None

    task.status = TASK_QUEUED_STATUS
    task.last_error = None
    task.lease_expires_at = None
    task.worker_task_id = None
    task.finished_at = None
    task.processed_items = 0
    record_audit_log(
        db,
        actor,
        "knowledge_task.retry",
        "knowledge_task",
        task.id,
        task.task_type,
        {"knowledge_base_id": knowledge_base.id, "document_id": task.document_id},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    await db.refresh(task)
    return task_to_response(task)


async def preview_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: User,
    settings: Settings,
    payload: KnowledgeDocumentParseRequest,
) -> list[KnowledgeDocumentChunkResponse]:
    options = parse_task_options(payload)
    try:
        chunks = await extract_document_chunk_contents(document, settings, options)
        vector_ids = await replace_document_chunks(db, knowledge_base, document, chunks)
    except KnowledgePipelineError as exc:
        document.status = DOCUMENT_PARSE_FAILED_STATUS
        document.last_error = task_error_message(exc)
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, document.last_error) from exc

    document.status = DOCUMENT_PARSED_STATUS
    document.last_error = None
    record_audit_log(
        db,
        actor,
        "knowledge_document.parse",
        "knowledge_document",
        document.id,
        document.filename,
        {"knowledge_base_id": knowledge_base.id, "chunk_count": len(chunks)},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    await asyncio.to_thread(delete_chroma_vectors, settings, knowledge_base.id, vector_ids)
    return await list_knowledge_document_chunks(db, knowledge_base, document)
