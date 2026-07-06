from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.core.config import Settings
from nexaflow.db.session import get_db
from nexaflow.identity.dependencies import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
)
from nexaflow.knowledge.schemas import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentResponse,
    ResourcePermissionResponse,
    ResourcePermissionUpsertRequest,
)
from nexaflow.knowledge.services import (
    create_knowledge_base,
    delete_knowledge_base_permanently,
    get_knowledge_base,
    list_knowledge_bases,
    list_knowledge_documents,
    list_resource_permissions,
    require_can_manage_permissions,
    require_knowledge_base_permission,
    revoke_resource_permission,
    update_knowledge_base,
    upload_knowledge_document,
    upsert_resource_permission,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/knowledge-bases", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeBaseResponse])
async def list_workspace_knowledge_bases(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnowledgeBaseResponse]:
    return await list_knowledge_bases(
        db,
        context.workspace.id,
        context.user,
        context.membership_role,
    )


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeBaseResponse:
    return await create_knowledge_base(db, context.workspace.id, payload, context.user)


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
async def get_workspace_knowledge_base(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeBaseResponse:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    permission = await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"view", "edit"},
    )
    return KnowledgeBaseResponse(
        id=knowledge_base.id,
        workspace_id=knowledge_base.workspace_id,
        name=knowledge_base.name,
        description=knowledge_base.description,
        status=knowledge_base.status,
        created_by_user_id=knowledge_base.created_by_user_id,
        created_at=knowledge_base.created_at,
        updated_at=knowledge_base.updated_at,
        permission=permission,
    )


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
async def patch_workspace_knowledge_base(
    knowledge_base_id: str,
    payload: KnowledgeBaseUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeBaseResponse:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"},
    )
    return await update_knowledge_base(db, knowledge_base, payload, context.user)


@router.delete("/{knowledge_base_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_knowledge_base(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await delete_knowledge_base_permanently(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        settings,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{knowledge_base_id}/documents", response_model=list[KnowledgeDocumentResponse])
async def list_workspace_knowledge_base_documents(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnowledgeDocumentResponse]:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"view", "edit"},
    )
    return await list_knowledge_documents(db, knowledge_base)


@router.post(
    "/{knowledge_base_id}/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_workspace_knowledge_base_document(
    knowledge_base_id: str,
    file: Annotated[UploadFile, File()],
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeDocumentResponse:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"},
    )
    return await upload_knowledge_document(
        db,
        knowledge_base,
        file,
        context.user,
        settings,
    )


@router.get("/{knowledge_base_id}/permissions", response_model=list[ResourcePermissionResponse])
async def list_workspace_knowledge_base_permissions(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ResourcePermissionResponse]:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    require_can_manage_permissions(knowledge_base, context.user, context.membership_role)
    return await list_resource_permissions(db, knowledge_base)


@router.put("/{knowledge_base_id}/permissions/{user_id}", response_model=ResourcePermissionResponse)
async def grant_workspace_knowledge_base_permission(
    knowledge_base_id: str,
    user_id: str,
    payload: ResourcePermissionUpsertRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResourcePermissionResponse:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    require_can_manage_permissions(knowledge_base, context.user, context.membership_role)
    return await upsert_resource_permission(
        db,
        knowledge_base,
        user_id,
        payload.permission,
        context.user,
    )


@router.delete("/{knowledge_base_id}/permissions/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_workspace_knowledge_base_permission(
    knowledge_base_id: str,
    user_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    require_can_manage_permissions(knowledge_base, context.user, context.membership_role)
    await revoke_resource_permission(db, knowledge_base, user_id, context.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
