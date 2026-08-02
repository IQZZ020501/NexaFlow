from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.core.config import Settings
from nexaflow.db.session import get_db
from nexaflow.identity.dependencies import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
)
from nexaflow.knowledge.lifecycle import delete_knowledge_document
from nexaflow.knowledge.processing import get_knowledge_document
from nexaflow.knowledge.services import (
    get_knowledge_base,
    require_knowledge_base_permission,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/knowledge-bases",
    tags=["knowledge"],
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
