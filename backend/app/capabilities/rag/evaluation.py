import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCaseMetrics:
    hit_at_k: int
    recall_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float


@dataclass(frozen=True)
class RetrievalAggregateMetrics:
    count: int
    mean_hit_at_k: float
    mean_recall_at_k: float
    mean_reciprocal_rank: float
    mean_ndcg_at_k: float
    p50_latency_ms: float
    p95_latency_ms: float


def retrieval_case_metrics(
    returned_document_ids: list[str],
    expected_document_ids: set[str],
    limit: int,
) -> RetrievalCaseMetrics:
    ranked = list(dict.fromkeys(returned_document_ids))[: max(0, limit)]
    relevant_ranks = [
        rank
        for rank, document_id in enumerate(ranked, start=1)
        if document_id in expected_document_ids
    ]
    relevant_count = len(relevant_ranks)
    recall = (
        relevant_count / len(expected_document_ids)
        if expected_document_ids
        else 0.0
    )
    reciprocal_rank = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_ranks)
    ideal_count = min(len(expected_document_ids), max(0, limit))
    ideal_dcg = sum(
        1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1)
    )
    return RetrievalCaseMetrics(
        hit_at_k=int(bool(relevant_ranks)),
        recall_at_k=recall,
        reciprocal_rank=reciprocal_rank,
        ndcg_at_k=dcg / ideal_dcg if ideal_dcg else 0.0,
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def aggregate_retrieval_metrics(
    metrics: list[RetrievalCaseMetrics],
    latencies_ms: list[float],
) -> RetrievalAggregateMetrics:
    count = len(metrics)
    divisor = count or 1
    return RetrievalAggregateMetrics(
        count=count,
        mean_hit_at_k=sum(item.hit_at_k for item in metrics) / divisor,
        mean_recall_at_k=sum(item.recall_at_k for item in metrics) / divisor,
        mean_reciprocal_rank=(
            sum(item.reciprocal_rank for item in metrics) / divisor
        ),
        mean_ndcg_at_k=sum(item.ndcg_at_k for item in metrics) / divisor,
        p50_latency_ms=_percentile(latencies_ms, 0.5),
        p95_latency_ms=_percentile(latencies_ms, 0.95),
    )
