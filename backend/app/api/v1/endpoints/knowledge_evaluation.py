from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    AsyncSession,
    Settings,
    WorkspaceContext,
    get_db,
    get_settings,
    get_workspace_context_from_path,
)
from app.application.knowledge import (
    create_evaluation_case,
    delete_evaluation_case,
    delete_evaluation_run,
    dispatch_knowledge_task,
    enqueue_evaluation_run,
    get_evaluation_run,
    get_evaluation_summary,
    get_knowledge_base,
    get_latest_evaluation_summary,
    list_evaluation_cases,
    list_evaluation_runs,
    require_knowledge_base_permission,
)
from app.schemas.knowledge import (
    KnowledgeEvaluationCaseCreateRequest,
    KnowledgeEvaluationCaseResponse,
    KnowledgeEvaluationRunRequest,
    KnowledgeEvaluationSummaryResponse,
    KnowledgeTaskResponse,
)

router = APIRouter(
    prefix=(
        "/workspaces/{workspace_id}/knowledge-bases/"
        "{knowledge_base_id}/evaluations"
    ),
    tags=["knowledge"],
)


async def _authorized_knowledge_base(
    db: AsyncSession,
    context: WorkspaceContext,
    knowledge_base_id: str,
    permissions: set[str],
) -> Any:
    knowledge_base = await get_knowledge_base(
        db,
        context.workspace.id,
        knowledge_base_id,
    )
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        permissions,
    )
    return knowledge_base


@router.get("/cases", response_model=list[KnowledgeEvaluationCaseResponse])
async def list_workspace_evaluation_cases(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KnowledgeEvaluationCaseResponse]:
    knowledge_base = await _authorized_knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await list_evaluation_cases(
        db,
        knowledge_base,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/cases",
    response_model=KnowledgeEvaluationCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_evaluation_case(
    knowledge_base_id: str,
    payload: KnowledgeEvaluationCaseCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeEvaluationCaseResponse:
    knowledge_base = await _authorized_knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"edit"},
    )
    return await create_evaluation_case(
        db,
        knowledge_base,
        payload,
        context.user,
    )


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_evaluation_case(
    knowledge_base_id: str,
    case_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    knowledge_base = await _authorized_knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"edit"},
    )
    await delete_evaluation_case(db, knowledge_base, case_id, context.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/runs", response_model=list[KnowledgeTaskResponse])
async def list_workspace_evaluation_runs(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[KnowledgeTaskResponse]:
    knowledge_base = await _authorized_knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await list_evaluation_runs(db, knowledge_base, limit=limit)


@router.post(
    "/runs",
    response_model=KnowledgeTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_workspace_evaluation_run(
    knowledge_base_id: str,
    payload: KnowledgeEvaluationRunRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeTaskResponse:
    knowledge_base = await _authorized_knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"edit"},
    )
    task = await enqueue_evaluation_run(
        db,
        knowledge_base,
        payload,
        context.user,
    )
    await dispatch_knowledge_task(task.id, settings)
    return task


@router.delete("/runs/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_evaluation_run(
    knowledge_base_id: str,
    task_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    knowledge_base = await _authorized_knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"edit"},
    )
    await delete_evaluation_run(db, knowledge_base, task_id, context.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/runs/{task_id}", response_model=KnowledgeTaskResponse)
async def get_workspace_evaluation_run(
    knowledge_base_id: str,
    task_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeTaskResponse:
    knowledge_base = await _authorized_knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await get_evaluation_run(db, knowledge_base, task_id)


@router.get(
    "/runs/{task_id}/results",
    response_model=KnowledgeEvaluationSummaryResponse,
)
async def get_workspace_evaluation_results(
    knowledge_base_id: str,
    task_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeEvaluationSummaryResponse:
    knowledge_base = await _authorized_knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await get_evaluation_summary(db, knowledge_base, task_id)


@router.get(
    "/results/latest",
    response_model=KnowledgeEvaluationSummaryResponse,
)
async def get_workspace_latest_evaluation_results(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeEvaluationSummaryResponse:
    knowledge_base = await _authorized_knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await get_latest_evaluation_summary(db, knowledge_base)
