"""Knowledge use cases.

Single facade consumed by the knowledge API endpoints: CRUD, document
lifecycle, task dispatch, retrieval orchestration, and object-file access.
Endpoints must not import ``app.shareddomain``, ``app.capabilities``, or
``app.infrastructure`` directly; this module is the only entry point.
"""

import asyncio
import logging
import time
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.schemas.knowledge import (
    KnowledgeDocumentResponse,
    KnowledgeQueryHitResponse,
    KnowledgeQueryRequest,
)
from app.capabilities.rag.retrieval import (
    QUERY_OVERFETCH_FACTOR,
    parent_context,
    reciprocal_rank_fusion,
    rerank_child_hits,
)
from app.ports.vector_store import VectorHit, query_vectors
from app.shareddomain.knowledge.lifecycle import (
    delete_knowledge_document,
    set_knowledge_document_active,
)
from app.shareddomain.knowledge.orchestration import (
    enqueue_index_knowledge_document,
    enqueue_parse_knowledge_document,
    enqueue_rebuild_knowledge_index,
    get_knowledge_document,
    list_knowledge_document_chunks,
    list_knowledge_tasks,
    resolve_embedding_model,
    retry_knowledge_task,
)
from app.entities.knowledge import (
    KnowledgeAsset,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
)
from app.entities.user import User
from app.shareddomain.knowledge.services import (
    create_knowledge_base,
    create_knowledge_documents_from_attachments,
    delete_knowledge_attachment,
    delete_knowledge_base_permanently as delete_knowledge_base_record,
    document_to_response,
    get_knowledge_base,
    get_knowledge_model,
    knowledge_document_path,
    knowledge_object_storage,
    list_knowledge_bases,
    list_knowledge_documents,
    list_resource_permissions,
    require_can_manage_permissions,
    require_knowledge_base_permission,
    revoke_resource_permission,
    test_knowledge_base_models,
    transfer_knowledge_base_owner,
    update_knowledge_base,
    upload_knowledge_attachment,
    upsert_resource_permission,
)
from app.tasks.knowledge import (
    enqueue_knowledge_storage_cleanup,
    enqueue_knowledge_task,
)

logger = get_logger(__name__)


async def delete_knowledge_base_permanently(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> None:
    cleanup_id = await delete_knowledge_base_record(
        db,
        knowledge_base,
        actor,
        workspace_role,
    )
    await enqueue_knowledge_storage_cleanup(cleanup_id, settings)


async def dispatch_knowledge_task(task_id: str, settings: Settings) -> None:
    try:
        await enqueue_knowledge_task(task_id, settings)
    except Exception as exc:
        log_error(logger, "Knowledge task dispatch failed.", exc, task_id=task_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Knowledge task queue is unavailable.",
        ) from exc


async def list_knowledge_documents_with_counts(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    include_staged: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeDocumentResponse]:
    documents = await list_knowledge_documents(
        db,
        knowledge_base,
        include_staged=include_staged,
        limit=limit,
        offset=offset,
    )
    chunk_counts = await knowledge_base_repository.count_document_chunks(
        db,
        knowledge_base,
    )
    return [
        document_to_response(document, chunk_count=chunk_counts.get(document.id, 0))
        for document in documents
    ]


async def document_response_with_chunk_count(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
) -> KnowledgeDocumentResponse:
    chunk_counts = await knowledge_base_repository.count_document_chunks(
        db,
        knowledge_base,
    )
    return document_to_response(
        document,
        chunk_count=chunk_counts.get(document.id, 0),
    )


async def get_knowledge_asset_file(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
    asset_id: str,
    settings: Settings,
) -> tuple[KnowledgeAsset, Path]:
    """Resolve a knowledge asset and its on-disk path for HTTP serving."""
    asset = await knowledge_base_repository.get_document_asset(
        db,
        knowledge_base,
        document_id,
        asset_id,
    )
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge asset not found.")
    asset_path = knowledge_object_storage(settings).path(asset.object_key)
    if not asset_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge asset file is missing.")
    return asset, asset_path


async def query_knowledge_base(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeQueryRequest,
    settings: Settings,
) -> list[KnowledgeQueryHitResponse]:
    started_at = time.perf_counter()
    candidate_limit = payload.limit * QUERY_OVERFETCH_FACTOR
    use_vector = payload.search_mode in {"embedding", "blend"}
    use_keywords = payload.search_mode in {"keywords", "blend"}
    embedding_model = None
    if use_vector:
        embedding_model = await resolve_embedding_model(db, knowledge_base)
        if embedding_model is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Embedding model is required.",
            )

    # Qdrant uses cosine similarity (keep scores >= threshold); the API uses
    # cosine distance (keep distances <= threshold).
    qdrant_score_threshold = (
        1.0 - payload.similarity if payload.similarity is not None else None
    )
    vector_task = (
        asyncio.to_thread(
            query_vectors,
            settings,
            knowledge_base.id,
            embedding_model,
            payload.query,
            candidate_limit,
            qdrant_score_threshold,
        )
        if use_vector
        else None
    )
    keyword_task = (
        knowledge_base_repository.query_keyword_chunk_ids(
            db,
            knowledge_base,
            payload.query,
            candidate_limit,
        )
        if use_keywords
        else None
    )
    if vector_task is not None and keyword_task is not None:
        vector_hits, keyword_chunk_ids = await asyncio.gather(
            vector_task, keyword_task
        )
    elif vector_task is not None:
        vector_hits = await vector_task
        keyword_chunk_ids = []
    else:
        vector_hits = []
        keyword_chunk_ids = await keyword_task
    ranked_hits = reciprocal_rank_fusion(vector_hits, keyword_chunk_ids)
    chunks = await knowledge_base_repository.list_chunks_by_ids(
        db,
        knowledge_base,
        [hit.chunk_id for hit in ranked_hits],
    )
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    documents = await knowledge_base_repository.list_active_documents_by_ids(
        db,
        knowledge_base,
        {chunk.document_id for chunk in chunks},
    )
    documents_by_id = {document.id: document for document in documents}

    valid_hits: list[tuple[KnowledgeDocumentChunk, VectorHit]] = []
    for hit in ranked_hits:
        chunk = chunks_by_id.get(hit.chunk_id)
        if chunk is None or chunk.document_id not in documents_by_id:
            continue
        valid_hits.append((chunk, hit))

    responses: list[KnowledgeQueryHitResponse] = []
    if not any(chunk.parent_id for chunk, _ in valid_hits):
        grouped_hits: dict[str, list[tuple[KnowledgeDocumentChunk, VectorHit]]] = {}
        for chunk, hit in valid_hits:
            grouped_hits.setdefault(chunk.document_id, []).append((chunk, hit))
        for document_id, hits in list(grouped_hits.items())[: payload.limit]:
            document = documents_by_id[document_id]
            representative_chunk, representative_hit = hits[0]
            responses.append(
                KnowledgeQueryHitResponse(
                    chunk_id=representative_chunk.id,
                    document_id=document_id,
                    document_filename=document.filename,
                    chunk_index=representative_chunk.chunk_index,
                    content="\n\n".join(
                        chunk.content
                        for chunk, _ in sorted(
                            hits,
                            key=lambda item: item[0].chunk_index,
                        )
                    ),
                    distance=representative_hit.distance,
                )
            )
    else:
        parents = await knowledge_base_repository.list_parent_chunks_by_ids(
            db,
            knowledge_base,
            {chunk.parent_id for chunk, _ in valid_hits if chunk.parent_id},
        )
        parents_by_id = {parent.id: parent for parent in parents}
        reranker_model = None
        if knowledge_base.reranker_model_id is not None:
            try:
                reranker_model = await get_knowledge_model(
                    db,
                    knowledge_base.workspace_id,
                    knowledge_base.reranker_model_id,
                    "RERANKER",
                )
            except HTTPException:
                reranker_model = None
        ordered_hits = await rerank_child_hits(
            reranker_model,
            payload.query,
            valid_hits,
            settings,
        )
        flat_hits_by_document: dict[
            str,
            list[tuple[KnowledgeDocumentChunk, VectorHit]],
        ] = {}
        for chunk, hit in ordered_hits:
            if chunk.parent_id is None:
                flat_hits_by_document.setdefault(chunk.document_id, []).append(
                    (chunk, hit)
                )

        seen_units: set[tuple[str, str]] = set()
        for chunk, hit in ordered_hits:
            unit = (
                ("parent", chunk.parent_id)
                if chunk.parent_id
                else ("document", chunk.document_id)
            )
            if unit in seen_units:
                continue
            seen_units.add(unit)
            document = documents_by_id[chunk.document_id]
            parent = parents_by_id.get(chunk.parent_id) if chunk.parent_id else None
            if chunk.parent_id and parent is None:
                continue
            content = (
                parent_context(parent, chunk)
                if parent is not None
                else "\n\n".join(
                    flat_chunk.content
                    for flat_chunk, _ in sorted(
                        flat_hits_by_document[chunk.document_id],
                        key=lambda item: item[0].chunk_index,
                    )
                )
            )
            responses.append(
                KnowledgeQueryHitResponse(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_filename=document.filename,
                    parent_id=parent.id if parent else None,
                    parent_title=parent.title if parent else None,
                    parent_index=parent.parent_index if parent else None,
                    chunk_index=chunk.chunk_index,
                    content=content,
                    distance=hit.distance,
                )
            )
            if len(responses) == payload.limit:
                break
    log_event(
        logger,
        logging.INFO,
        "Knowledge query completed.",
        knowledge_base_id=knowledge_base.id,
        hits=len(responses),
        duration_ms=round((time.perf_counter() - started_at) * 1000),
        query=payload.query[:120],
    )
    return responses


__all__ = [
    "create_knowledge_base",
    "create_knowledge_documents_from_attachments",
    "delete_knowledge_attachment",
    "delete_knowledge_base_permanently",
    "delete_knowledge_document",
    "dispatch_knowledge_task",
    "document_response_with_chunk_count",
    "document_to_response",
    "enqueue_index_knowledge_document",
    "enqueue_parse_knowledge_document",
    "enqueue_rebuild_knowledge_index",
    "get_knowledge_asset_file",
    "get_knowledge_base",
    "get_knowledge_document",
    "knowledge_document_path",
    "list_knowledge_bases",
    "list_knowledge_document_chunks",
    "list_knowledge_documents",
    "list_knowledge_documents_with_counts",
    "list_knowledge_tasks",
    "list_resource_permissions",
    "query_knowledge_base",
    "require_can_manage_permissions",
    "require_knowledge_base_permission",
    "retry_knowledge_task",
    "revoke_resource_permission",
    "set_knowledge_document_active",
    "test_knowledge_base_models",
    "transfer_knowledge_base_owner",
    "update_knowledge_base",
    "upload_knowledge_attachment",
    "upsert_resource_permission",
]
