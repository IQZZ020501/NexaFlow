from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    TASK_EVALUATE,
    TASK_FAILED_STATUS,
    TASK_SUCCEEDED_STATUS,
    KnowledgeBase,
    KnowledgeEvaluationCase,
    KnowledgeEvaluationExpectation,
    KnowledgeTask,
)
from app.entities.user import User
from app.infrastructure.model_utils import new_id
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.repositories import (
    knowledge_evaluation as evaluation_repository,
)
from app.schemas.knowledge import (
    KnowledgeEvaluationCaseCreateRequest,
    KnowledgeEvaluationCaseResponse,
    KnowledgeEvaluationRunRequest,
    KnowledgeGraphEvaluationExpectation,
    KnowledgeGraphEvaluationMetrics,
    KnowledgeTaskResponse,
)
from app.schemas.knowledge_graph import KnowledgeGraphQueryResultResponse
from app.shareddomain.audit.services import record_audit_log
from app.shareddomain.knowledge.permissions import require_knowledge_base_active
from app.shareddomain.knowledge.orchestration import (
    create_knowledge_task,
    task_to_response,
)
from app.shareddomain.knowledge_graph.schema import normalize_graph_name

EVALUATION_SIMILARITY_SEMANTICS = "normalized_cosine"


def _normalized_graph_values(values: list[str]) -> set[str]:
    return {
        normalized
        for value in values
        if (normalized := normalize_graph_name(value))
    }


def _set_precision_recall(
    returned: set[str],
    expected: set[str],
) -> tuple[float, float]:
    matched = len(returned & expected)
    return (
        matched / len(returned) if returned else 0.0,
        matched / len(expected) if expected else 0.0,
    )


def graph_evaluation_metrics(
    expectation: KnowledgeGraphEvaluationExpectation | None,
    graph: KnowledgeGraphQueryResultResponse | None,
) -> KnowledgeGraphEvaluationMetrics | None:
    if expectation is None or not any(
        (
            expectation.entity_names,
            expectation.predicates,
            expectation.path_entity_names,
            expectation.path_predicates,
        )
    ):
        return None

    expected_entities = _normalized_graph_values(
        [*expectation.entity_names, *expectation.path_entity_names]
    )
    expected_predicates = _normalized_graph_values(
        [*expectation.predicates, *expectation.path_predicates]
    )
    returned_entities = _normalized_graph_values(
        [item.canonical_name for item in graph.nodes]
    ) if graph is not None else set()
    returned_predicates = _normalized_graph_values(
        [item.predicate for item in graph.claims]
    ) if graph is not None else set()
    entity_precision, entity_recall = _set_precision_recall(
        returned_entities,
        expected_entities,
    )
    claim_precision, claim_recall = _set_precision_recall(
        returned_predicates,
        expected_predicates,
    )

    expected_path_entities = [
        normalize_graph_name(item) for item in expectation.path_entity_names
    ]
    expected_path_predicates = [
        normalize_graph_name(item) for item in expectation.path_predicates
    ]
    path_exact_match = 0
    path_edge_accuracy = 0.0
    if (
        graph is not None
        and len(expected_path_entities) >= 2
        and len(expected_path_predicates) == len(expected_path_entities) - 1
    ):
        for path in graph.paths:
            path_entities = [
                normalize_graph_name(item.canonical_name) for item in path.nodes
            ]
            path_predicates = [
                normalize_graph_name(item.predicate) for item in path.steps
            ]
            if (
                path_entities == expected_path_entities
                and path_predicates == expected_path_predicates
            ):
                path_exact_match = 1
            matched_edges = sum(
                index < len(path.steps)
                and index + 1 < len(path.nodes)
                and path_entities[index] == expected_path_entities[index]
                and path_predicates[index] == expected_path_predicates[index]
                and path_entities[index + 1] == expected_path_entities[index + 1]
                for index in range(len(expected_path_predicates))
            )
            path_edge_accuracy = max(
                path_edge_accuracy,
                matched_edges / len(expected_path_predicates),
            )

    claims = graph.claims if graph is not None else []
    citation_coverage = (
        sum(bool(item.evidence_ids) for item in claims) / len(claims)
        if claims
        else 0.0
    )
    return KnowledgeGraphEvaluationMetrics(
        entity_precision=entity_precision,
        entity_recall=entity_recall,
        claim_precision=claim_precision,
        claim_recall=claim_recall,
        path_exact_match=path_exact_match,
        path_edge_accuracy=path_edge_accuracy,
        citation_coverage=citation_coverage,
    )


def _case_responses(
    cases: list[KnowledgeEvaluationCase],
    expectations: list[KnowledgeEvaluationExpectation],
) -> list[KnowledgeEvaluationCaseResponse]:
    expected_by_case: dict[str, list[str]] = {}
    for expectation in expectations:
        expected_by_case.setdefault(expectation.case_id, []).append(
            expectation.document_id
        )
    return [
        KnowledgeEvaluationCaseResponse(
            id=case.id,
            workspace_id=case.workspace_id,
            knowledge_base_id=case.knowledge_base_id,
            question=case.question,
            expected_document_ids=expected_by_case.get(case.id, []),
            graph_expectation=(
                KnowledgeGraphEvaluationExpectation.model_validate(
                    case.graph_expectation
                )
                if case.graph_expectation
                else None
            ),
            created_by_user_id=case.created_by_user_id,
            created_at=case.created_at,
            updated_at=case.updated_at,
        )
        for case in cases
    ]


async def list_evaluation_cases(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[KnowledgeEvaluationCaseResponse]:
    cases = await evaluation_repository.list_cases(
        db,
        knowledge_base,
        limit=limit,
        offset=offset,
    )
    expectations = await evaluation_repository.list_expectations_for_cases(
        db,
        knowledge_base,
        {case.id for case in cases},
    )
    return _case_responses(cases, expectations)


async def create_evaluation_case(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeEvaluationCaseCreateRequest,
    actor: User,
) -> KnowledgeEvaluationCaseResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Evaluation text cannot be blank.",
        )
    knowledge_base = await knowledge_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
    document_ids = list(dict.fromkeys(payload.expected_document_ids))
    documents = await knowledge_repository.list_active_documents_by_ids(
        db,
        knowledge_base,
        set(document_ids),
    )
    if len(documents) != len(document_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expected document not found.")

    case = KnowledgeEvaluationCase(
        id=new_id(),
        workspace_id=knowledge_base.workspace_id,
        knowledge_base_id=knowledge_base.id,
        question=question,
        answer_points=[],
        graph_expectation=(
            payload.graph_expectation.model_dump(mode="json")
            if payload.graph_expectation is not None
            else {}
        ),
        created_by_user_id=actor.id,
    )
    expectations = [
        KnowledgeEvaluationExpectation(
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_id=knowledge_base.id,
            case_id=case.id,
            document_id=document_id,
        )
        for document_id in document_ids
    ]
    case = await evaluation_repository.create_case(db, case, expectations)
    record_audit_log(
        db,
        actor,
        "knowledge_evaluation_case.create",
        "knowledge_evaluation_case",
        case.id,
        case.id,
        {
            "knowledge_base_id": knowledge_base.id,
            "expected_document_count": len(document_ids),
            "has_graph_expectation": payload.graph_expectation is not None,
        },
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    return _case_responses([case], expectations)[0]


async def delete_evaluation_case(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    case_id: str,
    actor: User,
) -> None:
    knowledge_base = await knowledge_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    if (
        await knowledge_repository.get_open_knowledge_task(
            db,
            knowledge_base,
            TASK_EVALUATE,
            None,
        )
        is not None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Evaluation run is in progress.",
        )
    if not await evaluation_repository.delete_case(db, knowledge_base, case_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation case not found.")
    record_audit_log(
        db,
        actor,
        "knowledge_evaluation_case.delete",
        "knowledge_evaluation_case",
        case_id,
        case_id,
        {"knowledge_base_id": knowledge_base.id},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()


async def enqueue_evaluation_run(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeEvaluationRunRequest,
    actor: User,
) -> KnowledgeTaskResponse:
    knowledge_base = await knowledge_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = await evaluation_repository.list_cases_by_ids(
        db,
        knowledge_base,
        set(case_ids),
    )
    if len(cases) != len(case_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation case not found.")
    expectations = await evaluation_repository.list_expectations_for_cases(
        db,
        knowledge_base,
        set(case_ids),
    )
    expected_document_ids = {item.document_id for item in expectations}
    active_documents = await knowledge_repository.list_active_documents_by_ids(
        db,
        knowledge_base,
        expected_document_ids,
    )
    if len(active_documents) != len(expected_document_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Evaluation expected document is inactive.",
        )
    return await create_knowledge_task(
        db,
        knowledge_base,
        None,
        TASK_EVALUATE,
        actor,
        {
            "case_ids": case_ids,
            "limit": payload.limit,
            "search_mode": payload.search_mode,
            "similarity": payload.similarity,
            "similarity_semantics": EVALUATION_SIMILARITY_SEMANTICS,
            "include_references": payload.include_references,
            "graph_mode": payload.graph_mode,
            "max_hops": payload.max_hops,
        },
    )


async def get_evaluation_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
) -> KnowledgeTask:
    task = await knowledge_repository.get_knowledge_task_by_id(db, task_id)
    if (
        task is None
        or task.workspace_id != knowledge_base.workspace_id
        or task.knowledge_base_id != knowledge_base.id
        or task.task_type != TASK_EVALUATE
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation run not found.")
    return task


async def delete_evaluation_run(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
    actor: User,
) -> None:
    knowledge_base = await knowledge_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    task = await evaluation_repository.lock_evaluation_task(
        db,
        knowledge_base,
        task_id,
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation run not found.")
    if task.status not in {TASK_SUCCEEDED_STATUS, TASK_FAILED_STATUS}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only finished evaluation runs can be deleted.",
        )
    if not await evaluation_repository.delete_evaluation_task(
        db,
        knowledge_base,
        task.id,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation run not found.")
    record_audit_log(
        db,
        actor,
        "knowledge_evaluation_run.delete",
        "knowledge_task",
        task.id,
        task.id,
        {"knowledge_base_id": knowledge_base.id},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()


async def list_evaluation_runs(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    limit: int = 20,
) -> list[KnowledgeTaskResponse]:
    return [
        task_to_response(task)
        for task in await evaluation_repository.list_evaluation_tasks(
            db,
            knowledge_base,
            limit=limit,
        )
    ]


async def get_evaluation_run(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
) -> KnowledgeTaskResponse:
    return task_to_response(await get_evaluation_task(db, knowledge_base, task_id))
