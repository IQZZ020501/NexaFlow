from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.session import get_db
from app.api.deps import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
)
from app.services.knowledge_lifecycle import (
    delete_knowledge_document,
    set_knowledge_document_active,
)
from app.services.knowledge_processing import get_knowledge_document
from app.services.knowledge_repositories import count_document_chunks
from app.schemas.knowledge import (
    KnowledgeDocumentResponse,
    KnowledgeDocumentStatusUpdateRequest,
)
from app.services.knowledge import (
    document_to_response,
    get_knowledge_base,
    knowledge_document_path,
    require_knowledge_base_permission,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/knowledge-bases",
    tags=["knowledge"],
)


@router.get(
    "/{knowledge_base_id}/documents/{document_id}/download",
    response_class=FileResponse,
)
async def download_workspace_knowledge_base_document(
    knowledge_base_id: str,
    document_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
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
    document = await get_knowledge_document(db, knowledge_base, document_id)
    document_path = knowledge_document_path(settings, document.storage_path)
    if not document_path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Document file is missing.",
        )
    return FileResponse(
        document_path,
        media_type="application/octet-stream",
        filename=document.filename,
    )


@router.delete(
    "/{knowledge_base_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workspace_knowledge_base_document(
    knowledge_base_id: str,
    document_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
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
        {"edit"},
    )
    document = await get_knowledge_document(db, knowledge_base, document_id)
    await delete_knowledge_document(
        db,
        knowledge_base,
        document,
        context.user,
        settings,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{knowledge_base_id}/documents/{document_id}",
    response_model=KnowledgeDocumentResponse,
)
async def update_workspace_knowledge_base_document_status(
    knowledge_base_id: str,
    document_id: str,
    payload: KnowledgeDocumentStatusUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeDocumentResponse:
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
        {"edit"},
    )
    document = await get_knowledge_document(db, knowledge_base, document_id)
    await set_knowledge_document_active(
        db,
        knowledge_base,
        document,
        context.user,
        payload.is_active,
    )
    chunk_counts = await count_document_chunks(db, knowledge_base)
    return document_to_response(
        document,
        chunk_count=chunk_counts.get(document.id, 0),
    )
