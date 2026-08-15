"""Unified detailed knowledge retrieval for API, Agent, and Workflow callers."""

import asyncio
import logging
import time
from typing import Literal, cast

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.rag.retrieval import (
    MAX_RERANK_CHILDREN,
    QUERY_OVERFETCH_FACTOR,
    RankedHit,
    apply_rerank_results,
    parent_context,
    reciprocal_rank_fusion,
)
from app.entities.knowledge import (
    KnowledgeBase,
    KnowledgeDocumentChunk,
)
from app.infrastructure.config import Settings
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.model_utils import new_id
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.infrastructure.repositories import (
    knowledge_reference as knowledge_reference_repository,
)
from app.ports.llm import build_reranker
from app.ports.vector_store import query_vectors
from app.schemas.knowledge import (
    KnowledgeQueryHitResponse,
    KnowledgeQueryInspectResponse,
    KnowledgeQueryRequest,
    KnowledgeRetrievalTraceResponse,
)
from app.shareddomain.knowledge.orchestration import resolve_embedding_model
from app.shareddomain.knowledge.services import get_knowledge_model

logger = get_logger(__name__)
RerankStatus = Literal["not_configured", "applied", "fallback", "skipped"]
MAX_REFERENCE_TARGET_DOCUMENTS = 8
MAX_REFERENCES = 100


def _elapsed_ms(started_at: float) -> float:
    return round(max(0.0, (time.perf_counter() - started_at) * 1000), 3)


async def _query_candidates(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    query: str,
    candidate_limit: int,
    use_vector: bool,
    use_keywords: bool,
    embedding_model: object | None,
    score_threshold: float | None,
    settings: Settings,
    document_ids: set[str] | None = None,
):
    vector_task = None
    if use_vector:
        vector_args = (
            settings,
            knowledge_base.id,
            embedding_model,
            query,
            candidate_limit,
            score_threshold,
        )
        if document_ids is not None:
            vector_args += (document_ids,)
        vector_task = asyncio.to_thread(
            query_vectors,
            *vector_args,
        )
    keyword_task = None
    if use_keywords:
        keyword_args = (db, knowledge_base, query, candidate_limit)
        if document_ids is not None:
            keyword_args += (document_ids,)
        keyword_task = knowledge_base_repository.query_keyword_chunk_ids(
            *keyword_args,
        )
    if vector_task is not None and keyword_task is not None:
        return await asyncio.gather(vector_task, keyword_task)
    if vector_task is not None:
        return await vector_task, []
    if keyword_task is None:
        return [], []
    return [], await keyword_task


async def _rerank_hits(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    query: str,
    hits: list[tuple[KnowledgeDocumentChunk, RankedHit]],
    settings: Settings,
) -> tuple[list[tuple[KnowledgeDocumentChunk, RankedHit]], RerankStatus]:
    if knowledge_base.reranker_model_id is None:
        return hits, "not_configured"
    if not hits:
        return hits, "skipped"
    try:
        model = await get_knowledge_model(
            db,
            knowledge_base.workspace_id,
            knowledge_base.reranker_model_id,
            "RERANKER",
        )
    except HTTPException:
        return hits, "fallback"
    if model is None:
        return hits, "fallback"

    candidates = hits[:MAX_RERANK_CHILDREN]
    try:
        provider = build_reranker(settings, model)
        results = await asyncio.to_thread(
            provider.rerank,
            query,
            [chunk.search_text or chunk.content for chunk, _ in candidates],
        )
    except Exception:
        return hits, "fallback"

    ordered = apply_rerank_results(hits, results)
    if ordered is None:
        return hits, "fallback"
    return cast(list[tuple[KnowledgeDocumentChunk, RankedHit]], ordered), "applied"


async def retrieve_knowledge_base(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeQueryRequest,
    settings: Settings,
) -> KnowledgeQueryInspectResponse:
    """Run production retrieval once and return hits plus bounded diagnostics."""
    started_at = time.perf_counter()
    trace_id = new_id()
    stage_duration_ms: dict[str, float] = {}
    candidate_limit = payload.limit * QUERY_OVERFETCH_FACTOR
    use_vector = payload.search_mode in {"embedding", "blend"}
    use_keywords = payload.search_mode in {"keywords", "blend"}

    candidate_started_at = time.perf_counter()
    embedding_model = None
    if use_vector:
        embedding_model = await resolve_embedding_model(db, knowledge_base)
        if embedding_model is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Embedding model is required.",
            )

    qdrant_score_threshold = (
        1.0 - payload.similarity if payload.similarity is not None else None
    )
    vector_hits, keyword_chunk_ids = await _query_candidates(
        db,
        knowledge_base,
        payload.query,
        candidate_limit,
        use_vector,
        use_keywords,
        embedding_model,
        qdrant_score_threshold,
        settings,
    )
    direct_ranked_hits = reciprocal_rank_fusion(
        vector_hits,
        keyword_chunk_ids,
    )
    stage_duration_ms["candidates"] = _elapsed_ms(candidate_started_at)

    entity_started_at = time.perf_counter()
    direct_chunks = await knowledge_base_repository.list_chunks_by_ids(
        db,
        knowledge_base,
        [hit.chunk_id for hit in direct_ranked_hits],
    )
    direct_chunks_by_id = {chunk.id: chunk for chunk in direct_chunks}
    direct_documents = await knowledge_base_repository.list_active_documents_by_ids(
        db,
        knowledge_base,
        {chunk.document_id for chunk in direct_chunks},
    )
    direct_document_ids = {document.id for document in direct_documents}
    seed_hits = [
        (chunk, hit)
        for hit in direct_ranked_hits
        if (chunk := direct_chunks_by_id.get(hit.chunk_id)) is not None
        and chunk.document_id in direct_document_ids
    ]

    reference_chunk_ids: list[str] = []
    if payload.include_references and seed_hits:
        reference_started_at = time.perf_counter()
        references = (
            await knowledge_reference_repository.list_resolved_references_for_chunks(
                db,
                knowledge_base,
                [chunk.id for chunk, _ in seed_hits[: payload.limit]],
                MAX_REFERENCES,
            )
        )
        target_document_ids: list[str] = []
        for reference in references:
            target_document_id = reference.target_document_id
            if target_document_id and target_document_id not in target_document_ids:
                target_document_ids.append(target_document_id)
                if len(target_document_ids) == MAX_REFERENCE_TARGET_DOCUMENTS:
                    break
        allowed_target_ids = set(target_document_ids)
        selected_references = [
            reference
            for reference in references
            if reference.target_document_id in allowed_target_ids
        ]
        parent_ids = list(
            dict.fromkeys(
                reference.target_parent_id
                for reference in selected_references
                if reference.target_parent_id
            )
        )
        anchored_chunk_ids = (
            await knowledge_base_repository.list_indexed_chunk_ids_for_parent_ids(
                db,
                knowledge_base,
                parent_ids,
            )
        )
        document_scope_ids = {
            reference.target_document_id
            for reference in selected_references
            if reference.target_document_id and reference.target_parent_id is None
        }
        if document_scope_ids:
            scoped_vectors, scoped_keywords = await _query_candidates(
                db,
                knowledge_base,
                payload.query,
                candidate_limit,
                use_vector,
                use_keywords,
                embedding_model,
                qdrant_score_threshold,
                settings,
                document_scope_ids,
            )
            scoped_chunk_ids = [
                hit.chunk_id
                for hit in reciprocal_rank_fusion(scoped_vectors, scoped_keywords)
            ]
        else:
            scoped_chunk_ids = []
        reference_chunk_ids = list(
            dict.fromkeys([*anchored_chunk_ids, *scoped_chunk_ids])
        )[:candidate_limit]
        stage_duration_ms["references"] = _elapsed_ms(reference_started_at)

    ranked_hits = reciprocal_rank_fusion(
        vector_hits,
        keyword_chunk_ids,
        reference_chunk_ids,
    )
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
    valid_hits = [
        (chunk, hit)
        for hit in ranked_hits
        if (chunk := chunks_by_id.get(hit.chunk_id)) is not None
        and chunk.document_id in documents_by_id
    ]
    stage_duration_ms["entities"] = _elapsed_ms(entity_started_at)

    rerank_started_at = time.perf_counter()
    ordered_hits, rerank_status = await _rerank_hits(
        db,
        knowledge_base,
        payload.query,
        valid_hits,
        settings,
    )
    stage_duration_ms["rerank"] = _elapsed_ms(rerank_started_at)

    assemble_started_at = time.perf_counter()
    responses: list[KnowledgeQueryHitResponse] = []
    if not any(chunk.parent_id for chunk, _ in ordered_hits):
        grouped_hits: dict[
            str,
            list[tuple[KnowledgeDocumentChunk, RankedHit]],
        ] = {}
        for chunk, hit in ordered_hits:
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
                    sources=list(representative_hit.sources),
                    reference_hops=(
                        1 if representative_hit.reference_rank is not None else 0
                    ),
                    rerank_score=representative_hit.rerank_score,
                )
            )
    else:
        parents = await knowledge_base_repository.list_parent_chunks_by_ids(
            db,
            knowledge_base,
            {chunk.parent_id for chunk, _ in ordered_hits if chunk.parent_id},
        )
        parents_by_id = {parent.id: parent for parent in parents}
        flat_hits_by_document: dict[
            str,
            list[tuple[KnowledgeDocumentChunk, RankedHit]],
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
                    sources=list(hit.sources),
                    reference_hops=1 if hit.reference_rank is not None else 0,
                    rerank_score=hit.rerank_score,
                )
            )
            if len(responses) == payload.limit:
                break
    stage_duration_ms["assemble"] = _elapsed_ms(assemble_started_at)

    duration_ms = _elapsed_ms(started_at)
    bounded_stage_duration_ms = {
        stage: min(duration_ms, duration)
        for stage, duration in stage_duration_ms.items()
    }
    trace = KnowledgeRetrievalTraceResponse(
        trace_id=trace_id,
        search_mode=payload.search_mode,
        limit=payload.limit,
        max_distance=payload.similarity,
        vector_candidates=len(vector_hits),
        keyword_candidates=len(keyword_chunk_ids),
        reference_candidates=len(reference_chunk_ids),
        fused_candidates=len(ranked_hits),
        rerank_status=rerank_status,
        returned_hits=len(responses),
        duration_ms=duration_ms,
        stage_duration_ms=bounded_stage_duration_ms,
    )
    log_event(
        logger,
        logging.INFO,
        "Knowledge query completed.",
        trace_id=trace.trace_id,
        knowledge_base_id=knowledge_base.id,
        search_mode=trace.search_mode,
        vector_candidates=trace.vector_candidates,
        keyword_candidates=trace.keyword_candidates,
        reference_candidates=trace.reference_candidates,
        fused_candidates=trace.fused_candidates,
        rerank_status=trace.rerank_status,
        returned_hits=trace.returned_hits,
        duration_ms=trace.duration_ms,
    )
    return KnowledgeQueryInspectResponse(hits=responses, trace=trace)


async def query_knowledge_base(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeQueryRequest,
    settings: Settings,
) -> list[KnowledgeQueryHitResponse]:
    return (await retrieve_knowledge_base(db, knowledge_base, payload, settings)).hits


__all__ = ["query_knowledge_base", "retrieve_knowledge_base"]
