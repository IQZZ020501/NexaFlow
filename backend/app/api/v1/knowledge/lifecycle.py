from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
)
from app.application.knowledge.documents.service import (
    delete_knowledge_document,
    document_response_with_chunk_count,
    get_knowledge_asset_file,
    get_knowledge_base,
    get_knowledge_document,
    get_knowledge_document_file,
    get_knowledge_document_markdown_file,
    require_knowledge_base_permission,
    set_knowledge_document_active,
)
from app.infra.config.settings import Settings
from app.infra.db.session import get_db
from app.schemas.knowledge import (
    KnowledgeDocumentResponse,
    KnowledgeDocumentStatusUpdateRequest,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/knowledge-bases",
    tags=["knowledge"],
)


@router.get(
    "/{knowledge_base_id}/documents/{document_id}/download",
    response_class=StreamingResponse,
)
async def download_workspace_knowledge_base_document(
    knowledge_base_id: str,
    document_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    knowledge_base = await get_knowledge_base(
        db,
        context.workspace.id,
        knowledge_base_id,
    )
    permission = await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        {"view", "edit"},
    )
    document = await get_knowledge_document(
        db,
        knowledge_base,
        document_id,
        include_staged=permission == "edit",
    )
    content = await get_knowledge_document_file(settings, document.storage_path)
    await db.rollback()
    return StreamingResponse(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/{knowledge_base_id}/documents/{document_id}/content",
    response_class=StreamingResponse,
)
async def read_workspace_knowledge_document_markdown(
    knowledge_base_id: str,
    document_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    knowledge_base = await get_knowledge_base(
        db,
        context.workspace.id,
        knowledge_base_id,
    )
    permission = await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        {"view", "edit"},
    )
    document = await get_knowledge_document(
        db,
        knowledge_base,
        document_id,
        include_staged=permission == "edit",
    )
    content = await get_knowledge_document_markdown_file(document, settings)
    await db.rollback()
    return StreamingResponse(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/{knowledge_base_id}/documents/{document_id}/assets/{asset_id}",
    response_class=StreamingResponse,
)
async def read_workspace_knowledge_document_asset(
    knowledge_base_id: str,
    document_id: str,
    asset_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    knowledge_base = await get_knowledge_base(
        db,
        context.workspace.id,
        knowledge_base_id,
    )
    permission = await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        {"view", "edit"},
    )
    await get_knowledge_document(
        db,
        knowledge_base,
        document_id,
        include_staged=permission == "edit",
    )
    asset, content = await get_knowledge_asset_file(
        db,
        knowledge_base,
        document_id,
        asset_id,
        settings,
    )
    await db.rollback()
    return StreamingResponse(
        content,
        media_type=asset.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(asset.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
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
        {"edit"},
    )
    document = await get_knowledge_document(
        db, knowledge_base, document_id, include_staged=True
    )
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
    settings: Annotated[Settings, Depends(get_settings)],
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
        {"edit"},
    )
    document = await get_knowledge_document(
        db, knowledge_base, document_id, include_staged=True
    )
    document = await set_knowledge_document_active(
        db,
        knowledge_base,
        document,
        context.user,
        payload.is_active,
        settings,
    )
    return await document_response_with_chunk_count(
        db,
        knowledge_base,
        document,
    )
