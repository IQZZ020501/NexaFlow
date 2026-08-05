import asyncio
import logging
import time

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import Settings
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.shareddomain.knowledge.models import (
    KnowledgeBase,
    KnowledgeDocumentChunk,
)
from app.capabilities.rag.vector_store import VectorHit, query_vectors
from app.shareddomain.knowledge.orchestration import resolve_embedding_model
from app.schemas.knowledge import (
    KnowledgeQueryHitResponse,
    KnowledgeQueryRequest,
)

logger = get_logger(__name__)

QUERY_OVERFETCH_FACTOR = 5
RRF_K = 60


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

    grouped_hits: dict[str, list[tuple[KnowledgeDocumentChunk, VectorHit]]] = {}
    for hit in ranked_hits:
        chunk = chunks_by_id.get(hit.chunk_id)
        if chunk is None or chunk.document_id not in documents_by_id:
            continue
        grouped_hits.setdefault(chunk.document_id, []).append((chunk, hit))

    responses: list[KnowledgeQueryHitResponse] = []
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
