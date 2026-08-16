from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import (
    TASK_EVALUATE,
    TASK_FAILED_STATUS,
    TASK_SUCCEEDED_STATUS,
    KnowledgeBase,
    KnowledgeEvaluationCase,
    KnowledgeEvaluationExpectation,
    KnowledgeEvaluationResult,
    KnowledgeTask,
)
from app.infrastructure.repositories.mapping import (
    apply_to_orm,
    save,
    to_entity,
    to_orm,
)
from app.shareddomain.knowledge.models import (
    KnowledgeEvaluationCase as KnowledgeEvaluationCaseORM,
    KnowledgeEvaluationExpectation as KnowledgeEvaluationExpectationORM,
    KnowledgeEvaluationResult as KnowledgeEvaluationResultORM,
    KnowledgeTask as KnowledgeTaskORM,
)


async def create_case(
    db: AsyncSession,
    case: KnowledgeEvaluationCase,
    expectations: list[KnowledgeEvaluationExpectation],
) -> KnowledgeEvaluationCase:
    row = await save(db, KnowledgeEvaluationCaseORM, case)
    for expectation in expectations:
        db.add(to_orm(KnowledgeEvaluationExpectationORM, expectation))
    await db.flush()
    return to_entity(KnowledgeEvaluationCase, row)


async def list_cases(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[KnowledgeEvaluationCase]:
    rows = await db.scalars(
        select(KnowledgeEvaluationCaseORM)
        .where(
            KnowledgeEvaluationCaseORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeEvaluationCaseORM.knowledge_base_id == knowledge_base.id,
        )
        .order_by(
            KnowledgeEvaluationCaseORM.created_at.desc(),
            KnowledgeEvaluationCaseORM.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(KnowledgeEvaluationCase, row) for row in rows]


async def list_cases_by_ids(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    case_ids: set[str],
) -> list[KnowledgeEvaluationCase]:
    if not case_ids:
        return []
    rows = await db.scalars(
        select(KnowledgeEvaluationCaseORM).where(
            KnowledgeEvaluationCaseORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeEvaluationCaseORM.knowledge_base_id == knowledge_base.id,
            KnowledgeEvaluationCaseORM.id.in_(case_ids),
        )
    )
    return [to_entity(KnowledgeEvaluationCase, row) for row in rows]


async def get_case(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    case_id: str,
) -> KnowledgeEvaluationCase | None:
    row = await db.scalar(
        select(KnowledgeEvaluationCaseORM).where(
            KnowledgeEvaluationCaseORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeEvaluationCaseORM.knowledge_base_id == knowledge_base.id,
            KnowledgeEvaluationCaseORM.id == case_id,
        )
    )
    return to_entity(KnowledgeEvaluationCase, row) if row else None


async def delete_case(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    case_id: str,
) -> bool:
    result = await db.execute(
        delete(KnowledgeEvaluationCaseORM).where(
            KnowledgeEvaluationCaseORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeEvaluationCaseORM.knowledge_base_id == knowledge_base.id,
            KnowledgeEvaluationCaseORM.id == case_id,
        )
    )
    return result.rowcount == 1


async def lock_evaluation_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
) -> KnowledgeTask | None:
    row = await db.scalar(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.id == task_id,
            KnowledgeTaskORM.task_type == TASK_EVALUATE,
        )
        .with_for_update()
    )
    return to_entity(KnowledgeTask, row) if row else None


async def delete_evaluation_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
) -> bool:
    result = await db.execute(
        delete(KnowledgeTaskORM).where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.id == task_id,
            KnowledgeTaskORM.task_type == TASK_EVALUATE,
            KnowledgeTaskORM.status.in_([TASK_SUCCEEDED_STATUS, TASK_FAILED_STATUS]),
        )
    )
    return result.rowcount == 1


async def list_expectations_for_cases(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    case_ids: set[str],
) -> list[KnowledgeEvaluationExpectation]:
    if not case_ids:
        return []
    rows = await db.scalars(
        select(KnowledgeEvaluationExpectationORM).where(
            KnowledgeEvaluationExpectationORM.workspace_id
            == knowledge_base.workspace_id,
            KnowledgeEvaluationExpectationORM.knowledge_base_id
            == knowledge_base.id,
            KnowledgeEvaluationExpectationORM.case_id.in_(case_ids),
        )
    )
    return [to_entity(KnowledgeEvaluationExpectation, row) for row in rows]


async def get_result(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
    case_id: str,
) -> KnowledgeEvaluationResult | None:
    row = await db.scalar(
        select(KnowledgeEvaluationResultORM).where(
            KnowledgeEvaluationResultORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeEvaluationResultORM.knowledge_base_id == knowledge_base.id,
            KnowledgeEvaluationResultORM.task_id == task_id,
            KnowledgeEvaluationResultORM.case_id == case_id,
        )
    )
    return to_entity(KnowledgeEvaluationResult, row) if row else None


async def upsert_result(
    db: AsyncSession,
    result: KnowledgeEvaluationResult,
) -> KnowledgeEvaluationResult:
    statement = (
        select(KnowledgeEvaluationResultORM)
        .where(
            KnowledgeEvaluationResultORM.workspace_id == result.workspace_id,
            KnowledgeEvaluationResultORM.knowledge_base_id
            == result.knowledge_base_id,
            KnowledgeEvaluationResultORM.task_id == result.task_id,
            KnowledgeEvaluationResultORM.case_id == result.case_id,
        )
        .with_for_update()
    )
    row = await db.scalar(statement)
    if row is None:
        try:
            async with db.begin_nested():
                row = to_orm(KnowledgeEvaluationResultORM, result)
                db.add(row)
                await db.flush()
            return to_entity(KnowledgeEvaluationResult, row)
        except IntegrityError:
            row = await db.scalar(statement)
            if row is None:
                raise
    if row.error is None and result.error is not None:
        return to_entity(KnowledgeEvaluationResult, row)
    result.id = row.id
    apply_to_orm(row, result)
    await db.flush()
    return to_entity(KnowledgeEvaluationResult, row)


async def count_results(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(KnowledgeEvaluationResultORM)
            .where(
                KnowledgeEvaluationResultORM.workspace_id
                == knowledge_base.workspace_id,
                KnowledgeEvaluationResultORM.knowledge_base_id
                == knowledge_base.id,
                KnowledgeEvaluationResultORM.task_id == task_id,
            )
        )
        or 0
    )


async def list_results_for_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
) -> list[KnowledgeEvaluationResult]:
    rows = await db.scalars(
        select(KnowledgeEvaluationResultORM)
        .where(
            KnowledgeEvaluationResultORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeEvaluationResultORM.knowledge_base_id == knowledge_base.id,
            KnowledgeEvaluationResultORM.task_id == task_id,
        )
        .order_by(KnowledgeEvaluationResultORM.created_at, KnowledgeEvaluationResultORM.id)
    )
    return [to_entity(KnowledgeEvaluationResult, row) for row in rows]


async def list_evaluation_tasks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    limit: int = 20,
) -> list[KnowledgeTask]:
    rows = await db.scalars(
        select(KnowledgeTaskORM)
        .where(
            KnowledgeTaskORM.workspace_id == knowledge_base.workspace_id,
            KnowledgeTaskORM.knowledge_base_id == knowledge_base.id,
            KnowledgeTaskORM.task_type == TASK_EVALUATE,
        )
        .order_by(KnowledgeTaskORM.created_at.desc(), KnowledgeTaskORM.id.desc())
        .limit(limit)
    )
    return [to_entity(KnowledgeTask, row) for row in rows]
