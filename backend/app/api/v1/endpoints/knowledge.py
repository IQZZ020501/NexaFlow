from typing import Annotated

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.api.deps import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
)
from app.schemas.knowledge import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentChunkResponse,
    KnowledgeDocumentParseRequest,
    KnowledgeDocumentResponse,
    KnowledgeModelTestRequest,
    KnowledgeModelTestResponse,
    KnowledgeTaskResponse,
    ResourcePermissionResponse,
    ResourcePermissionUpsertRequest,
)
from app.shareddomain.knowledge.processing import (
    enqueue_index_knowledge_document,
    enqueue_parse_knowledge_document,
    enqueue_rebuild_knowledge_index,
    get_knowledge_document,
    list_knowledge_document_chunks,
    list_knowledge_tasks,
    retry_knowledge_task,
)
from app.infrastructure.repositories.knowledge import (
    count_document_chunks,
)
from app.shareddomain.knowledge.services import (
    create_knowledge_base,
    delete_knowledge_base_permanently,
    get_knowledge_base,
    list_knowledge_bases,
    list_knowledge_documents,
    document_to_response,
    list_resource_permissions,
    require_can_manage_permissions,
    require_knowledge_base_permission,
    revoke_resource_permission,
    test_knowledge_base_models,
    update_knowledge_base,
    upload_knowledge_document,
    upsert_resource_permission,
)
from app.tasks.knowledge import enqueue_knowledge_task

router = APIRouter(prefix="/workspaces/{workspace_id}/knowledge-bases", tags=["knowledge"])


async def dispatch_knowledge_task(task_id: str, settings: Settings) -> None:
    try:
        await enqueue_knowledge_task(task_id, settings)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Knowledge task queue is unavailable.",
        ) from exc


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
        embedding_model_id=knowledge_base.embedding_model_id,
        reranker_model_id=knowledge_base.reranker_model_id,
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
    include_staged: Annotated[bool, Query()] = False,
) -> list[KnowledgeDocumentResponse]:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"} if include_staged else {"view", "edit"},
    )
    documents = await list_knowledge_documents(
        db,
        knowledge_base,
        include_staged=include_staged,
    )
    chunk_counts = await count_document_chunks(db, knowledge_base)
    return [
        document_to_response(document, chunk_count=chunk_counts.get(document.id, 0))
        for document in documents
    ]


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
    auto_parse: Annotated[bool, Form()] = True,
) -> KnowledgeDocumentResponse:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"},
    )
    uploaded = await upload_knowledge_document(
        db,
        knowledge_base,
        file,
        context.user,
        settings,
    )
    if not auto_parse:
        return uploaded

    document = await get_knowledge_document(db, knowledge_base, uploaded.id)
    task = await enqueue_parse_knowledge_document(db, knowledge_base, document, context.user)
    try:
        await dispatch_knowledge_task(task.id, settings)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_503_SERVICE_UNAVAILABLE:
            raise
        await db.refresh(document)
    return document_to_response(document)


@router.get(
    "/{knowledge_base_id}/documents/{document_id}/chunks",
    response_model=list[KnowledgeDocumentChunkResponse],
)
async def list_workspace_knowledge_document_chunks(
    knowledge_base_id: str,
    document_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnowledgeDocumentChunkResponse]:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"view", "edit"},
    )
    document = await get_knowledge_document(db, knowledge_base, document_id)
    return await list_knowledge_document_chunks(db, knowledge_base, document)


@router.get(
    "/{knowledge_base_id}/documents/{document_id}/tasks",
    response_model=list[KnowledgeTaskResponse],
)
async def list_workspace_knowledge_document_tasks(
    knowledge_base_id: str,
    document_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnowledgeTaskResponse]:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"view", "edit"},
    )
    document = await get_knowledge_document(db, knowledge_base, document_id)
    return await list_knowledge_tasks(db, knowledge_base, document)


@router.post(
    "/{knowledge_base_id}/documents/{document_id}/parse",
    response_model=KnowledgeTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def parse_workspace_knowledge_base_document(
    knowledge_base_id: str,
    document_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: Annotated[KnowledgeDocumentParseRequest | None, Body()] = None,
) -> KnowledgeTaskResponse:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"},
    )
    document = await get_knowledge_document(db, knowledge_base, document_id)
    task = await enqueue_parse_knowledge_document(db, knowledge_base, document, context.user, payload)
    await dispatch_knowledge_task(task.id, settings)
    return task


@router.post(
    "/{knowledge_base_id}/documents/{document_id}/index",
    response_model=KnowledgeTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def index_workspace_knowledge_base_document(
    knowledge_base_id: str,
    document_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeTaskResponse:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"},
    )
    document = await get_knowledge_document(db, knowledge_base, document_id)
    task = await enqueue_index_knowledge_document(db, knowledge_base, document, context.user)
    await dispatch_knowledge_task(task.id, settings)
    return task


@router.post(
    "/{knowledge_base_id}/model-test",
    response_model=KnowledgeModelTestResponse,
)
async def test_workspace_knowledge_base_models(
    knowledge_base_id: str,
    payload: KnowledgeModelTestRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeModelTestResponse:
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
    return await test_knowledge_base_models(db, knowledge_base, payload, settings)


@router.get("/{knowledge_base_id}/tasks", response_model=list[KnowledgeTaskResponse])
async def list_workspace_knowledge_base_tasks(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnowledgeTaskResponse]:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"view", "edit"},
    )
    return await list_knowledge_tasks(db, knowledge_base)


@router.post(
    "/{knowledge_base_id}/tasks/{task_id}/retry",
    response_model=KnowledgeTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_workspace_knowledge_task(
    knowledge_base_id: str,
    task_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeTaskResponse:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"},
    )
    task = await retry_knowledge_task(db, knowledge_base, task_id, context.user)
    await dispatch_knowledge_task(task.id, settings)
    return task


@router.post(
    "/{knowledge_base_id}/rebuild-index",
    response_model=KnowledgeTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rebuild_workspace_knowledge_base_index(
    knowledge_base_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeTaskResponse:
    knowledge_base = await get_knowledge_base(db, context.workspace.id, knowledge_base_id)
    await require_knowledge_base_permission(
        db,
        knowledge_base,
        context.user,
        context.membership_role,
        {"edit"},
    )
    task = await enqueue_rebuild_knowledge_index(db, knowledge_base, context.user)
    await dispatch_knowledge_task(task.id, settings)
    return task


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
