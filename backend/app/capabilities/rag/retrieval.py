import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from app.capabilities.llm.models import RegisteredModel
from app.capabilities.llm.runtime import ModelProviderError, build_registered_reranker
from app.infrastructure.config import Settings
from app.capabilities.rag.vector_store import VectorHit

QUERY_OVERFETCH_FACTOR = 5
RRF_K = 60
MAX_RERANK_CHILDREN = 10
MAX_PARENT_CONTEXT_CHARS = 2000


@dataclass(frozen=True)
class RankedHit:
    chunk_id: str
    distance: float | None
    rrf_score: float
    vector_rank: int | None
    keyword_rank: int | None
    reference_rank: int | None
    sources: tuple[str, ...]
    rerank_score: float | None = None


class ParentChunk(Protocol):
    content: str
    title: str | None
    parent_index: int | None


class ChildChunk(Protocol):
    id: str
    document_id: str
    chunk_index: int
    parent_id: str | None
    start_offset: int | None
    end_offset: int | None
    content: str


def reciprocal_rank_fusion(
    vector_hits: list[VectorHit],
    keyword_chunk_ids: list[str],
    reference_chunk_ids: Sequence[str] = (),
) -> list[RankedHit]:
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    ranks: dict[str, dict[str, int]] = {}
    rankings = (
        ("vector", [hit.chunk_id for hit in vector_hits]),
        ("keywords", keyword_chunk_ids),
        ("reference", reference_chunk_ids),
    )
    for source, ranking in rankings:
        for rank, chunk_id in enumerate(dict.fromkeys(ranking), start=1):
            first_seen.setdefault(chunk_id, len(first_seen))
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (RRF_K + rank)
            ranks.setdefault(chunk_id, {})[source] = rank

    distances = {hit.chunk_id: hit.distance for hit in reversed(vector_hits)}
    return [
        RankedHit(
            chunk_id=chunk_id,
            distance=distances.get(chunk_id),
            rrf_score=scores[chunk_id],
            vector_rank=ranks[chunk_id].get("vector"),
            keyword_rank=ranks[chunk_id].get("keywords"),
            reference_rank=ranks[chunk_id].get("reference"),
            sources=tuple(
                source for source, _ in rankings if source in ranks[chunk_id]
            ),
        )
        for chunk_id in sorted(
            scores,
            key=lambda chunk_id: (-scores[chunk_id], first_seen[chunk_id]),
        )
    ]


def parent_context(
    parent: ParentChunk,
    chunk: ChildChunk,
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
    reranker_model: RegisteredModel | None,
    query: str,
    hits: list[tuple[ChildChunk, RankedHit | VectorHit]],
    settings: Settings,
) -> list[tuple[ChildChunk, RankedHit | VectorHit]]:
    if reranker_model is None or not hits:
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
    return apply_rerank_results(hits, results) or hits


def apply_rerank_results(
    hits: list[tuple[ChildChunk, RankedHit | VectorHit]],
    results: object,
) -> list[tuple[ChildChunk, RankedHit | VectorHit]] | None:
    if not isinstance(results, list):
        return None

    candidates = hits[:MAX_RERANK_CHILDREN]
    scored: list[tuple[int, float]] = []
    for fallback_index, result in enumerate(results):
        if not isinstance(result, dict):
            return None
        index = result.get("index", fallback_index)
        score = result.get("relevance_score", 0)
        if not (
            isinstance(index, int)
            and not isinstance(index, bool)
            and 0 <= index < len(candidates)
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and math.isfinite(score)
        ):
            return None
        scored.append((index, float(score)))
    if not scored:
        return None

    ordered_indexes = list(
        dict.fromkeys(
            index
            for index, _ in sorted(scored, key=lambda item: item[1], reverse=True)
        )
    )
    ordered_indexes.extend(
        index for index in range(len(candidates)) if index not in ordered_indexes
    )
    scores_by_index: dict[int, float] = {}
    for index, score in scored:
        scores_by_index[index] = max(score, scores_by_index.get(index, score))

    ordered_candidates = []
    for index in ordered_indexes:
        chunk, hit = candidates[index]
        if isinstance(hit, RankedHit) and index in scores_by_index:
            hit = replace(hit, rerank_score=scores_by_index[index])
        ordered_candidates.append((chunk, hit))
    return ordered_candidates + hits[len(candidates) :]
