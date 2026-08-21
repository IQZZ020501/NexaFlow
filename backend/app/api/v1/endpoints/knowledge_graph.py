from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    Settings,
    WorkspaceContext,
    get_db,
    get_settings as get_app_settings,
    get_workspace_context_from_path,
)
from app.application import knowledge_graph as graph_application
from app.schemas.knowledge import KnowledgeTaskResponse
from app.schemas.knowledge_graph import (
    KnowledgeGraphEntityDetailResponse,
    KnowledgeGraphEntityListResponse,
    KnowledgeGraphNeighborhoodRequest,
    KnowledgeGraphPathRequest,
    KnowledgeGraphQueryResultResponse,
    KnowledgeGraphReviewDecisionRequest,
    KnowledgeGraphReviewListResponse,
    KnowledgeGraphSchemaResponse,
    KnowledgeGraphSchemaUpdateRequest,
    KnowledgeGraphSettingsResponse,
    KnowledgeGraphSettingsUpdateRequest,
    KnowledgeGraphStatusResponse,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/knowledge-bases/{knowledge_base_id}/graph",
    tags=["knowledge-graph"],
)


async def _knowledge_base(
    db: AsyncSession,
    context: WorkspaceContext,
    knowledge_base_id: str,
    permissions: set[str],
):
    return await graph_application.require_graph_knowledge_base(
        db,
        context.workspace.id,
        knowledge_base_id,
        context.user,
        context.membership_role,
        permissions,
    )


@router.get("/settings", response_model=KnowledgeGraphSettingsResponse)
async def get_graph_settings_endpoint(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeGraphSettingsResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await graph_application.get_graph_settings(knowledge_base)


@router.patch("/settings", response_model=KnowledgeGraphSettingsResponse)
async def patch_settings(
    knowledge_base_id: str,
    payload: KnowledgeGraphSettingsUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeGraphSettingsResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"edit"},
    )
    return await graph_application.update_graph_settings(
        db,
        knowledge_base,
        payload,
        context.user,
        settings,
    )


@router.get("/schema", response_model=KnowledgeGraphSchemaResponse | None)
async def get_schema(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeGraphSchemaResponse | None:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await graph_application.get_graph_schema(db, knowledge_base)


@router.put("/schema", response_model=KnowledgeGraphSchemaResponse)
async def put_schema(
    knowledge_base_id: str,
    payload: KnowledgeGraphSchemaUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeGraphSchemaResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"edit"},
    )
    return await graph_application.update_graph_schema(
        db,
        knowledge_base,
        payload,
        context.user,
    )


@router.get("/status", response_model=KnowledgeGraphStatusResponse)
async def get_status(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeGraphStatusResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await graph_application.get_graph_status(db, knowledge_base)


@router.post(
    "/rebuild",
    response_model=KnowledgeTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rebuild(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeTaskResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"edit"},
    )
    return await graph_application.rebuild_graph(
        db,
        knowledge_base,
        context.user,
        settings,
    )


@router.get("/entities", response_model=KnowledgeGraphEntityListResponse)
async def list_entities(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    query: Annotated[str | None, Query(max_length=500)] = None,
    entity_type: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeGraphEntityListResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await graph_application.list_graph_entities(
        db,
        knowledge_base,
        query=query,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
    )


@router.get("/overview", response_model=KnowledgeGraphQueryResultResponse)
async def overview(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeGraphQueryResultResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await graph_application.get_graph_overview(db, knowledge_base)


@router.get(
    "/entities/{entity_id}",
    response_model=KnowledgeGraphEntityDetailResponse,
)
async def get_entity(
    knowledge_base_id: str,
    entity_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeGraphEntityDetailResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await graph_application.get_graph_entity(
        db,
        knowledge_base,
        entity_id,
    )


@router.post("/path", response_model=KnowledgeGraphQueryResultResponse)
async def path(
    knowledge_base_id: str,
    payload: KnowledgeGraphPathRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeGraphQueryResultResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await graph_application.query_graph_path(
        db,
        knowledge_base,
        payload,
        settings,
    )


@router.post("/neighborhood", response_model=KnowledgeGraphQueryResultResponse)
async def neighborhood(
    knowledge_base_id: str,
    payload: KnowledgeGraphNeighborhoodRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeGraphQueryResultResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await graph_application.query_graph_neighborhood(
        db,
        knowledge_base,
        payload,
        settings,
    )


@router.post(
    "/import",
    response_model=KnowledgeTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_records(
    knowledge_base_id: str,
    file: Annotated[UploadFile, File()],
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeTaskResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"edit"},
    )
    return await graph_application.import_and_dispatch_graph_records(
        db,
        knowledge_base,
        file,
        context.user,
        settings,
    )


@router.get("/reviews", response_model=KnowledgeGraphReviewListResponse)
async def list_reviews(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeGraphReviewListResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"view", "edit"},
    )
    return await graph_application.list_graph_reviews(
        db,
        knowledge_base,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/reviews/{review_id}/resolve",
    response_model=KnowledgeTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resolve_review(
    knowledge_base_id: str,
    review_id: str,
    payload: KnowledgeGraphReviewDecisionRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeTaskResponse:
    knowledge_base = await _knowledge_base(
        db,
        context,
        knowledge_base_id,
        {"edit"},
    )
    return await graph_application.resolve_graph_review(
        db,
        knowledge_base,
        review_id,
        payload,
        context.user,
        settings,
    )
