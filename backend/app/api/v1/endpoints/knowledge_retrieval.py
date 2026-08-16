from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.api.deps import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
)
from app.application.knowledge import (
    get_knowledge_base,
    query_knowledge_base,
    require_knowledge_base_permission,
    retrieve_knowledge_base,
)
from app.schemas.knowledge import (
    KnowledgeQueryHitResponse,
    KnowledgeQueryInspectResponse,
    KnowledgeQueryRequest,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/knowledge-bases",
    tags=["knowledge"],
)


@router.post(
    "/{knowledge_base_id}/query",
    response_model=list[KnowledgeQueryHitResponse],
)
async def query_workspace_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeQueryRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnowledgeQueryHitResponse]:
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
        {"view", "edit"},
    )
    return await query_knowledge_base(db, knowledge_base, payload, settings)


@router.post(
    "/{knowledge_base_id}/query/inspect",
    response_model=KnowledgeQueryInspectResponse,
)
async def inspect_workspace_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeQueryRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeQueryInspectResponse:
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
        {"view", "edit"},
    )
    return await retrieve_knowledge_base(db, knowledge_base, payload, settings)
