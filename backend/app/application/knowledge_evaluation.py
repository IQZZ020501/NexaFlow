import asyncio
import time
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.knowledge_retrieval import (
    normalized_cosine_similarity,
    retrieve_knowledge_base,
)
from app.capabilities.rag.evaluation import (
    RetrievalCaseMetrics,
    aggregate_retrieval_metrics,
    retrieval_case_metrics,
)
from app.entities.knowledge import (
    KnowledgeBase,
    KnowledgeEvaluationResult,
    KnowledgeTask,
)
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import (
    knowledge_evaluation as evaluation_repository,
)
from app.ports.parsing import KnowledgePipelineError
from app.schemas.knowledge import (
    KnowledgeEvaluationResultResponse,
    KnowledgeEvaluationRunRequest,
    KnowledgeEvaluationSummaryResponse,
    KnowledgeGraphEvaluationExpectation,
    KnowledgeQueryRequest,
)
from app.shareddomain.knowledge.evaluation import (
    EVALUATION_SIMILARITY_SEMANTICS,
    get_evaluation_task,
    graph_evaluation_metrics,
)
from app.shareddomain.knowledge.orchestration import (
    task_error_message,
    task_to_response,
)
from app.shareddomain.knowledge.task_runner import (
    TASK_LEASE_SECONDS,
    ensure_knowledge_task_lease,
)


async def _persist_owned_progress(
    db: AsyncSession,
    task: KnowledgeTask,
) -> None:
    if task.worker_task_id is None or not (
        await knowledge_repository.update_owned_knowledge_task_progress(
            db,
            task.id,
            task.worker_task_id,
            task.total_items,
            task.processed_items,
            utc_now() + timedelta(seconds=TASK_LEASE_SECONDS),
        )
    ):
        raise KnowledgePipelineError("Knowledge task lease was lost.")


def _evaluation_run_request(options: dict[str, Any]) -> KnowledgeEvaluationRunRequest:
    normalized_options = dict(options)
    if (
        normalized_options.get("similarity_semantics")
        != EVALUATION_SIMILARITY_SEMANTICS
    ):
        normalized_options["similarity"] = normalized_cosine_similarity(
            normalized_options.get("similarity")
        )
    return KnowledgeEvaluationRunRequest.model_validate(normalized_options)


async def run_evaluation_task(
    db: AsyncSession,
    task: KnowledgeTask,
    knowledge_base: KnowledgeBase,
    _actor: User,
    settings: Settings,
    lease_lost: asyncio.Event,
) -> None:
    payload = _evaluation_run_request(task.options)
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = await evaluation_repository.list_cases_by_ids(
        db,
        knowledge_base,
        set(case_ids),
    )
    if len(cases) != len(case_ids):
        raise KnowledgePipelineError("Evaluation case no longer exists.")
    cases_by_id = {case.id: case for case in cases}
    graph_expectations = {
        case.id: (
            KnowledgeGraphEvaluationExpectation.model_validate(
                case.graph_expectation
            )
            if case.graph_expectation
            else None
        )
        for case in cases
    }
    expectations = await evaluation_repository.list_expectations_for_cases(
        db,
        knowledge_base,
        set(case_ids),
    )
    expected_by_case: dict[str, set[str]] = {}
    for expectation in expectations:
        expected_by_case.setdefault(expectation.case_id, set()).add(
            expectation.document_id
        )

    task.total_items = len(case_ids)
    task.processed_items = await evaluation_repository.count_results(
        db,
        knowledge_base,
        task.id,
    )
    await _persist_owned_progress(db, task)
    await db.commit()

    for case_id in case_ids:
        ensure_knowledge_task_lease(lease_lost)
        existing = await evaluation_repository.get_result(
            db,
            knowledge_base,
            task.id,
            case_id,
        )
        if existing is not None and existing.error is None:
            continue

        started_at = time.perf_counter()
        try:
            retrieval = await retrieve_knowledge_base(
                db,
                knowledge_base,
                KnowledgeQueryRequest(
                    query=cases_by_id[case_id].question,
                    limit=payload.limit,
                    search_mode=payload.search_mode,
                    similarity=payload.similarity,
                    include_references=payload.include_references,
                    graph_mode=payload.graph_mode,
                    max_hops=payload.max_hops,
                ),
                settings,
            )
            ensure_knowledge_task_lease(lease_lost)
            returned_document_ids = list(
                dict.fromkeys(hit.document_id for hit in retrieval.hits)
            )
            metrics = retrieval_case_metrics(
                returned_document_ids,
                expected_by_case.get(case_id, set()),
                payload.limit,
            )
            result = existing or KnowledgeEvaluationResult(
                id=new_id(),
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_id=task.id,
                case_id=case_id,
            )
            result.returned_document_ids = returned_document_ids
            result.returned_chunk_ids = [hit.chunk_id for hit in retrieval.hits]
            result.hit_at_k = metrics.hit_at_k
            result.recall_at_k = metrics.recall_at_k
            result.reciprocal_rank = metrics.reciprocal_rank
            result.ndcg_at_k = metrics.ndcg_at_k
            result.latency_ms = retrieval.trace.duration_ms
            result.trace = {
                **retrieval.trace.model_dump(mode="json"),
                "graph": (
                    retrieval.graph.model_dump(mode="json")
                    if retrieval.graph is not None
                    else None
                ),
            }
            graph_metrics = graph_evaluation_metrics(
                graph_expectations[case_id],
                retrieval.graph,
            )
            result.graph_metrics = (
                graph_metrics.model_dump(mode="json")
                if graph_metrics is not None
                else {}
            )
            result.error = None
        except Exception as exc:
            if lease_lost.is_set():
                raise KnowledgePipelineError("Knowledge task lease was lost.") from exc
            await db.rollback()
            result = existing or KnowledgeEvaluationResult(
                id=new_id(),
                workspace_id=knowledge_base.workspace_id,
                knowledge_base_id=knowledge_base.id,
                task_id=task.id,
                case_id=case_id,
            )
            result.returned_document_ids = []
            result.returned_chunk_ids = []
            result.hit_at_k = 0
            result.recall_at_k = 0.0
            result.reciprocal_rank = 0.0
            result.ndcg_at_k = 0.0
            result.latency_ms = round(
                (time.perf_counter() - started_at) * 1000,
                3,
            )
            result.trace = {}
            result.graph_metrics = {}
            result.error = task_error_message(exc)

        if existing is None:
            task.processed_items += 1
        await _persist_owned_progress(db, task)
        await evaluation_repository.upsert_result(db, result)
        await db.commit()

    failed_count = sum(
        result.error is not None
        for result in await evaluation_repository.list_results_for_task(
            db,
            knowledge_base,
            task.id,
        )
    )
    if failed_count:
        raise KnowledgePipelineError(
            f"{failed_count} evaluation case(s) failed."
        )


async def get_evaluation_summary(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
) -> KnowledgeEvaluationSummaryResponse:
    task = await get_evaluation_task(db, knowledge_base, task_id)
    results = await evaluation_repository.list_results_for_task(
        db,
        knowledge_base,
        task.id,
    )
    positions = {
        case_id: index
        for index, case_id in enumerate(task.options.get("case_ids", []))
    }
    results.sort(key=lambda result: positions.get(result.case_id, len(positions)))
    cases = await evaluation_repository.list_cases_by_ids(
        db,
        knowledge_base,
        {result.case_id for result in results},
    )
    questions = {case.id: case.question for case in cases}
    successful = [result for result in results if result.error is None]
    aggregate = aggregate_retrieval_metrics(
        [
            RetrievalCaseMetrics(
                hit_at_k=result.hit_at_k,
                recall_at_k=result.recall_at_k,
                reciprocal_rank=result.reciprocal_rank,
                ndcg_at_k=result.ndcg_at_k,
            )
            for result in successful
        ],
        [result.latency_ms for result in successful],
    )
    return KnowledgeEvaluationSummaryResponse(
        task=task_to_response(task),
        count=aggregate.count,
        failed_count=len(results) - len(successful),
        mean_hit_at_k=aggregate.mean_hit_at_k,
        mean_recall_at_k=aggregate.mean_recall_at_k,
        mean_reciprocal_rank=aggregate.mean_reciprocal_rank,
        mean_ndcg_at_k=aggregate.mean_ndcg_at_k,
        p50_latency_ms=aggregate.p50_latency_ms,
        p95_latency_ms=aggregate.p95_latency_ms,
        results=[
            KnowledgeEvaluationResultResponse(
                id=result.id,
                case_id=result.case_id,
                question=questions.get(result.case_id, ""),
                returned_document_ids=result.returned_document_ids,
                returned_chunk_ids=result.returned_chunk_ids,
                hit_at_k=result.hit_at_k,
                recall_at_k=result.recall_at_k,
                reciprocal_rank=result.reciprocal_rank,
                ndcg_at_k=result.ndcg_at_k,
                latency_ms=result.latency_ms,
                trace=result.trace,
                graph_metrics=result.graph_metrics or None,
                error=result.error,
                created_at=result.created_at,
            )
            for result in results
        ],
    )


async def get_latest_evaluation_summary(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> KnowledgeEvaluationSummaryResponse:
    tasks = await evaluation_repository.list_evaluation_tasks(
        db,
        knowledge_base,
        limit=1,
    )
    if not tasks:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation run not found.")
    return await get_evaluation_summary(db, knowledge_base, tasks[0].id)
