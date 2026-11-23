"""Paginated knowledge read endpoints; legacy list responses stay compatible."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_workspace_context_from_path
from app.application.knowledge.documents.service import (
    document_response_with_chunk_count,
    get_knowledge_base,
    get_knowledge_document,
    get_knowledge_document_options,
    get_knowledge_document_page,
    get_knowledge_task_page,
    require_knowledge_base_permission,
)
from app.infra.db.session import get_db
from app.schemas.knowledge.contracts import (
    KnowledgeDocumentOptionResponse,
    KnowledgeDocumentPageResponse,
    KnowledgeDocumentResponse,
    KnowledgeDocumentSort,
    KnowledgeTaskPageResponse,
)

router = APIRouter()


@router.get("/{knowledge_base_id}/documents/page")
async def read_document_page(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str, Query(max_length=255)] = "",
    sort_by: KnowledgeDocumentSort = "created_at",
    sort_direction: Literal["asc", "desc"] = "desc",
    include_staged: bool = False,
) -> KnowledgeDocumentPageResponse:
    kb = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db, kb, context.user, {"edit"} if include_staged else {"view", "edit"}
    )
    return await get_knowledge_document_page(
        db,
        kb,
        limit=limit,
        offset=offset,
        search=search,
        sort_by=sort_by,
        sort_direction=sort_direction,
        include_staged=include_staged,
    )


@router.get("/{knowledge_base_id}/documents/options")
async def read_document_options(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnowledgeDocumentOptionResponse]:
    kb = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(db, kb, context.user, {"view", "edit"})
    return await get_knowledge_document_options(db, kb)


@router.get("/{knowledge_base_id}/documents/{document_id}")
async def read_document(
    knowledge_base_id: str,
    document_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeDocumentResponse:
    kb = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    permission = await require_knowledge_base_permission(
        db, kb, context.user, {"view", "edit"}
    )
    document = await get_knowledge_document(
        db, kb, document_id, include_staged=permission == "edit"
    )
    return await document_response_with_chunk_count(db, kb, document)


@router.get("/{knowledge_base_id}/tasks/page")
async def read_task_page(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeTaskPageResponse:
    kb = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    permission = await require_knowledge_base_permission(
        db, kb, context.user, {"view", "edit"}
    )
    return await get_knowledge_task_page(
        db, kb, limit=limit, offset=offset, exclude_staged=permission != "edit"
    )
