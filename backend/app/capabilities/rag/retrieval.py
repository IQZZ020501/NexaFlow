import asyncio
import logging
import time

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.llm.runtime import ModelProviderError, build_registered_reranker
from app.infrastructure.config import Settings
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.shareddomain.knowledge.models import (
    KnowledgeBase,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
)
from app.capabilities.rag.vector_store import VectorHit, query_vectors
from app.shareddomain.knowledge.orchestration import resolve_embedding_model
from app.shareddomain.knowledge.services import get_knowledge_model
from app.schemas.knowledge import (
    KnowledgeQueryHitResponse,
    KnowledgeQueryRequest,
)

logger = get_logger(__name__)

QUERY_OVERFETCH_FACTOR = 5
RRF_K = 60
MAX_RERANK_CHILDREN = 10
MAX_PARENT_CONTEXT_CHARS = 2000


def reciprocal_rank_fusion(
    vector_hits: list[VectorHit],
    keyword_chunk_ids: list[str],
) -> list[VectorHit]:
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    rankings = ([hit.chunk_id for hit in vector_hits], keyword_chunk_ids)
    for ranking in rankings:
        for rank, chunk_id in enumerate(dict.fromkeys(ranking), start=1):
            first_seen.setdefault(chunk_id, len(first_seen))
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (RRF_K + rank)

    distances = {hit.chunk_id: hit.distance for hit in reversed(vector_hits)}
    return [
        VectorHit(chunk_id=chunk_id, distance=distances.get(chunk_id))
        for chunk_id in sorted(
            scores,
            key=lambda chunk_id: (-scores[chunk_id], first_seen[chunk_id]),
        )
    ]


def parent_context(
    parent: KnowledgeDocumentParentChunk,
    chunk: KnowledgeDocumentChunk,
) -> str:
    if len(parent.content) <= MAX_PARENT_CONTEXT_CHARS:
        return parent.content
    if chunk.start_offset is None or chunk.end_offset is None:
        return parent.content[:MAX_PARENT_CONTEXT_CHARS]

    center = (chunk.start_offset + chunk.end_offset) // 2
    start = max(
        0,
        min(
            center - MAX_PARENT_CONTEXT_CHARS // 2,
            len(parent.content) - MAX_PARENT_CONTEXT_CHARS,
        ),
    )
    return parent.content[start : start + MAX_PARENT_CONTEXT_CHARS]


async def rerank_child_hits(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    query: str,
    hits: list[tuple[KnowledgeDocumentChunk, VectorHit]],
    settings: Settings,
) -> list[tuple[KnowledgeDocumentChunk, VectorHit]]:
    if knowledge_base.reranker_model_id is None or not hits:
        return hits
    try:
        reranker_model = await get_knowledge_model(
            db,
            knowledge_base.workspace_id,
            knowledge_base.reranker_model_id,
            "RERANKER",
        )
    except HTTPException:
        return hits
    if reranker_model is None:
        return hits

    candidates = hits[:MAX_RERANK_CHILDREN]
    try:
        results = await asyncio.to_thread(
            build_registered_reranker(reranker_model, settings).rerank,
            query,
            [chunk.content for chunk, _ in candidates],
        )
    except ModelProviderError:
        return hits

    scored: list[tuple[int, float]] = []
    for fallback_index, result in enumerate(results):
        if not isinstance(result, dict):
            continue
        index = result.get("index", fallback_index)
        score = result.get("relevance_score", 0)
        if isinstance(index, int) and 0 <= index < len(candidates) and isinstance(score, (int, float)):
            scored.append((index, float(score)))
    if not scored:
        return hits

    ordered_indexes = list(
        dict.fromkeys(
            index
            for index, _ in sorted(scored, key=lambda item: item[1], reverse=True)
        )
    )
    ordered_indexes.extend(
        index for index in range(len(candidates)) if index not in ordered_indexes
    )
    return [candidates[index] for index in ordered_indexes] + hits[len(candidates) :]


async def query_knowledge_base(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeQueryRequest,
    settings: Settings,
) -> list[KnowledgeQueryHitResponse]:
    started_at = time.perf_counter()
    embedding_model = await resolve_embedding_model(db, knowledge_base)
    if embedding_model is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Embedding model is required.",
        )

    candidate_limit = payload.limit * QUERY_OVERFETCH_FACTOR
    vector_hits, keyword_chunk_ids = await asyncio.gather(
        asyncio.to_thread(
            query_vectors,
            settings,
            knowledge_base.id,
            embedding_model,
            payload.query,
            candidate_limit,
        ),
        knowledge_base_repository.query_keyword_chunk_ids(
            db,
            knowledge_base,
            payload.query,
            candidate_limit,
        ),
    )
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
        grouped_hits: dict[
            str,
            list[tuple[KnowledgeDocumentChunk, VectorHit]],
        ] = {}
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
        ordered_hits = await rerank_child_hits(
            db,
            knowledge_base,
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
