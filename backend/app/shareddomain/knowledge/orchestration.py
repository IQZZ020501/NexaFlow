import asyncio
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.shareddomain.audit.services import record_audit_log
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger
from app.infrastructure.model_utils import new_id
from app.entities.user import User
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.entities.knowledge import (
    CHUNK_INDEX_FAILED_STATUS,
    CHUNK_INDEXED_STATUS,
    CHUNK_PREVIEW_STATUS,
    DOCUMENT_DELETED_STATUS,
    DOCUMENT_INDEX_FAILED_STATUS,
    DOCUMENT_INDEX_QUEUED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    DOCUMENT_INDEXING_STATUS,
    DOCUMENT_PARSE_FAILED_STATUS,
    DOCUMENT_PARSE_QUEUED_STATUS,
    DOCUMENT_PARSED_STATUS,
    DOCUMENT_PARSING_STATUS,
    DOCUMENT_STAGED_META_KEY,
    TASK_FAILED_STATUS,
    TASK_INDEX,
    TASK_PARSE,
    TASK_QUEUED_STATUS,
    TASK_REBUILD_INDEX,
    TASK_SUCCEEDED_STATUS,
    KnowledgeAsset,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeTask,
)
from app.ports.parsing import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DocumentChunkDrafts,
    KnowledgePipelineError,
    SPLIT_SEPARATORS,
    build_flat_chunks,
    build_hierarchical_chunks,
    chunk_token_count,
    clean_text,
    extract_document,
    split_text,
)
from app.ports.vector_store import delete_vectors
from app.schemas.knowledge import (
    KnowledgeAssetResponse,
    KnowledgeDocumentChunkResponse,
    KnowledgeDocumentParseRequest,
    KnowledgeTaskResponse,
)
from app.shareddomain.knowledge.permissions import require_knowledge_base_active
from app.shareddomain.knowledge.services import (
    get_knowledge_model,
    knowledge_document_path,
    knowledge_object_storage,
)
from app.ports.llm import RegisteredModel

logger = get_logger(__name__)

MAX_TASK_ATTEMPTS = 3
ALLOWED_CLEANING_RULES = {"trim_lines", "collapse_spaces", "remove_empty_lines"}
DEFAULT_PARSE_OPTIONS: dict[str, Any] = {
    "strategy": "flat",
    "chunk_size": CHUNK_SIZE,
    "chunk_overlap": CHUNK_OVERLAP,
    "split_separator": "\n\n",
    "cleaning_rules": [],
    "auto_index": True,
}


def asset_to_response(asset: KnowledgeAsset) -> KnowledgeAssetResponse:
    return KnowledgeAssetResponse(
        id=asset.id,
        kind="image",
        filename=asset.filename,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        alt_text=asset.alt_text,
    )


def chunk_to_response(
    chunk: KnowledgeDocumentChunk,
    parent: KnowledgeDocumentParentChunk | None = None,
    assets: list[KnowledgeAsset] | None = None,
) -> KnowledgeDocumentChunkResponse:
    return KnowledgeDocumentChunkResponse(
        id=chunk.id,
        workspace_id=chunk.workspace_id,
        knowledge_base_id=chunk.knowledge_base_id,
        document_id=chunk.document_id,
        parent_id=chunk.parent_id,
        parent_title=parent.title if parent else None,
        parent_index=parent.parent_index if parent else None,
        chunk_index=chunk.chunk_index,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        content=chunk.content,
        char_count=chunk.char_count,
        token_count=chunk.token_count,
        vector_id=chunk.vector_id,
        status=chunk.status,
        images=[asset_to_response(asset) for asset in assets or []],
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
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeDocumentChunkResponse]:
    chunks = await knowledge_base_repository.list_document_chunks(
        db,
        knowledge_base,
        document.id,
        limit,
        offset,
    )
    parents = await knowledge_base_repository.list_parent_chunks_by_ids(
        db,
        knowledge_base,
        {chunk.parent_id for chunk in chunks if chunk.parent_id},
    )
    parents_by_id = {parent.id: parent for parent in parents}
    asset_rows = await knowledge_base_repository.list_chunk_assets(
        db,
        knowledge_base,
        {chunk.id for chunk in chunks},
    )
    assets_by_chunk: dict[str, list[KnowledgeAsset]] = {}
    for chunk_asset, asset in asset_rows:
        assets_by_chunk.setdefault(chunk_asset.chunk_id, []).append(asset)
    return [
        chunk_to_response(
            chunk,
            parents_by_id.get(chunk.parent_id),
            assets_by_chunk.get(chunk.id, []),
        )
        for chunk in chunks
    ]


async def list_knowledge_tasks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeTaskResponse]:
    tasks = await knowledge_base_repository.list_knowledge_tasks(
        db,
        knowledge_base,
        document.id if document else None,
        limit,
        offset,
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
) -> DocumentChunkDrafts:
    text, assets = await asyncio.to_thread(
        extract_document,
        document.filename,
        document.content_type,
        knowledge_document_path(settings, document.storage_path),
    )
    text = clean_text(
        text,
        options["cleaning_rules"],
        preserve_empty_lines=options["split_separator"] == "\n\n",
    )
    chunks = (
        build_hierarchical_chunks(
            text,
            options["chunk_size"],
            options["chunk_overlap"],
            options["split_separator"],
        )
        if options["strategy"] == "hierarchical"
        else build_flat_chunks(
            split_text(
                text,
                options["chunk_size"],
                options["chunk_overlap"],
                options["split_separator"],
            )
        )
    )
    if not chunks.children:
        raise KnowledgePipelineError("Document has no extractable chunks.")
    return DocumentChunkDrafts(
        parents=chunks.parents,
        children=chunks.children,
        assets=assets,
    )


async def replace_document_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    chunks: DocumentChunkDrafts,
    settings: Settings,
) -> tuple[list[str], list[str], list[str]]:
    existing_chunks = await knowledge_base_repository.list_document_chunks(
        db,
        knowledge_base,
        document.id,
    )
    vector_ids = [chunk.vector_id for chunk in existing_chunks if chunk.vector_id]
    stale_asset_keys = await knowledge_base_repository.delete_document_assets(
        db,
        document.id,
    )
    await knowledge_base_repository.delete_document_chunks(db, document.id)

    storage = knowledge_object_storage(settings)
    written_asset_keys: list[str] = []
    assets: list[KnowledgeAsset] = []
    parents: list[KnowledgeDocumentParentChunk] = []
    children: list[KnowledgeDocumentChunk] = []
    chunk_asset_links: list[tuple[str, str, int]] = []
    try:
        for index, draft in enumerate(chunks.assets):
            object_key = (
                f"{document.workspace_id}/{document.knowledge_base_id}/assets/"
                f"{document.id}/{draft.id}/{draft.filename}"
            )
            storage.put_bytes(object_key, draft.content)
            written_asset_keys.append(object_key)
            assets.append(
                KnowledgeAsset(
                    id=draft.id,
                    workspace_id=document.workspace_id,
                    knowledge_base_id=document.knowledge_base_id,
                    document_id=document.id,
                    asset_index=index,
                    kind="image",
                    filename=draft.filename,
                    content_type=draft.content_type,
                    size_bytes=len(draft.content),
                    object_key=object_key,
                    alt_text=draft.alt_text,
                    meta={},
                )
            )

        for index, draft in enumerate(chunks.parents):
            parents.append(
                KnowledgeDocumentParentChunk(
                    id=new_id(),
                    workspace_id=document.workspace_id,
                    knowledge_base_id=document.knowledge_base_id,
                    document_id=document.id,
                    parent_index=index,
                    title=draft.title,
                    content=draft.content,
                    char_count=len(draft.content),
                    meta={},
                )
            )

        for index, draft in enumerate(chunks.children):
            parent = (
                parents[draft.parent_index]
                if draft.parent_index is not None
                else None
            )
            if parent is not None and (
                draft.start_offset is None
                or draft.end_offset is None
                or (
                    parent.content[draft.start_offset : draft.end_offset]
                    != draft.content
                    and not draft.content.endswith(
                        parent.content[draft.start_offset : draft.end_offset]
                    )
                )
            ):
                raise KnowledgePipelineError("Knowledge chunk offsets are invalid.")
            chunk = KnowledgeDocumentChunk(
                id=new_id(),
                workspace_id=document.workspace_id,
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                parent_id=parent.id if parent else None,
                chunk_index=index,
                start_offset=draft.start_offset,
                end_offset=draft.end_offset,
                content=draft.content,
                char_count=len(draft.content),
                token_count=chunk_token_count(draft.content),
                status=CHUNK_PREVIEW_STATUS,
            )
            children.append(chunk)
            for asset_index, document_asset_index in enumerate(
                draft.asset_indexes
            ):
                if not 0 <= document_asset_index < len(chunks.assets):
                    continue
                chunk_asset_links.append(
                    (
                        chunk.id,
                        chunks.assets[document_asset_index].id,
                        asset_index,
                    )
                )

        await knowledge_base_repository.replace_document_chunks(
            db,
            knowledge_base,
            document.id,
            parents,
            children,
            assets,
            chunk_asset_links,
        )
    except Exception:
        for object_key in written_asset_keys:
            storage.delete(object_key)
        raise
    return vector_ids, stale_asset_keys, written_asset_keys


async def create_knowledge_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument | None,
    task_type: str,
    actor: User,
    options: dict[str, Any] | None = None,
) -> KnowledgeTaskResponse:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
    document_id = document.id if document else None
    if await get_conflicting_open_task(db, knowledge_base, task_type, document_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge task is already running.")

    if task_type in {TASK_INDEX, TASK_REBUILD_INDEX}:
        had_embedding_model = knowledge_base.embedding_model_id is not None
        embedding_model = await resolve_embedding_model(db, knowledge_base)
        if embedding_model is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Embedding model is required.",
            )
        if not had_embedding_model:
            await knowledge_base_repository.set_knowledge_base_embedding_model_id(
                db,
                knowledge_base.id,
                embedding_model.id,
            )

    total_items = 0
    if task_type == TASK_INDEX and document is not None:
        chunks = await knowledge_base_repository.list_document_chunks(db, knowledge_base, document.id)
        if not chunks:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Document has no preview chunks.")
        total_items = len(chunks)
        document.status = DOCUMENT_INDEX_QUEUED_STATUS
        document.meta = {
            **(document.meta or {}),
            DOCUMENT_STAGED_META_KEY: False,
        }
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

    if document is not None:
        await knowledge_base_repository.save_knowledge_document(db, document)

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
    task = await knowledge_base_repository.create_knowledge_task(db, task)
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
    task = await knowledge_base_repository.refresh_knowledge_task(db, task)
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
    return await create_knowledge_task(db, knowledge_base, document, TASK_INDEX, actor)


async def enqueue_rebuild_knowledge_index(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
) -> KnowledgeTaskResponse:
    return await create_knowledge_task(db, knowledge_base, None, TASK_REBUILD_INDEX, actor)


async def retry_knowledge_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
    actor: User,
) -> KnowledgeTaskResponse:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
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
            document.meta = {
                **(document.meta or {}),
                DOCUMENT_STAGED_META_KEY: False,
            }
        document.last_error = None
        await knowledge_base_repository.save_knowledge_document(db, document)

    task.status = TASK_QUEUED_STATUS
    task.last_error = None
    task.lease_expires_at = None
    task.worker_task_id = None
    task.finished_at = None
    task.processed_items = 0
    await knowledge_base_repository.save_knowledge_task(db, task)
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
    task = await knowledge_base_repository.refresh_knowledge_task(db, task)
    return task_to_response(task)
