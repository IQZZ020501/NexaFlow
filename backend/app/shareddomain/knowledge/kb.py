"""Knowledge base CRUD, model resolution, and model testing."""

import asyncio

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import KnowledgeBase
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.infrastructure.repositories import resource_permission as permission_repository
from app.infrastructure.validation import normalize_name
from app.ports import model_registry as model_repository
from app.ports.llm import (
    ModelProviderError,
    ModelProviderStatusError,
    RegisteredModel,
    build_embeddings,
    build_reranker,
)
from app.schemas.knowledge import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseListItemResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
    KnowledgeModelTestRequest,
    KnowledgeModelTestResponse,
)
from app.shareddomain.audit.services import record_audit_log
from app.shareddomain.knowledge.cleanup import create_knowledge_storage_cleanup
from app.shareddomain.knowledge.permissions import (
    RESOURCE_TYPE,
    effective_permission,
    get_user_grant,
    require_knowledge_base_active,
    require_knowledge_base_permission,
)

ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
KNOWLEDGE_BASE_STATUSES = {ACTIVE_STATUS, ARCHIVED_STATUS}


def knowledge_base_to_response(
    knowledge_base: KnowledgeBase,
    permission: str,
) -> KnowledgeBaseResponse:
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


def normalize_optional_model_id(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


async def get_knowledge_model(
    db: AsyncSession,
    workspace_id: str,
    model_id: str | None,
    model_type: str,
    *,
    use_default: bool = False,
) -> RegisteredModel | None:
    model_id = normalize_optional_model_id(model_id)
    if model_id is None:
        if use_default:
            return await get_default_knowledge_model(db, workspace_id, model_type)
        return None
    model = await model_repository.get_registered_model_by_id(db, model_id)
    if model is None or model.workspace_id != workspace_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Knowledge model not found.",
        )
    if model.model_type != model_type:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Knowledge model must be {model_type}.",
        )
    if model.status != ACTIVE_STATUS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Knowledge model is disabled.",
        )
    return model


async def get_default_knowledge_model(
    db: AsyncSession,
    workspace_id: str,
    model_type: str,
) -> RegisteredModel | None:
    models = await model_repository.list_registered_models(db, workspace_id)
    return next(
        (
            model
            for model in models
            if model.model_type == model_type and model.status == ACTIVE_STATUS
        ),
        None,
    )


def require_can_manage_permissions(
    knowledge_base: KnowledgeBase,
    actor: User,
    workspace_role: str | None,
) -> None:
    if workspace_role == "admin" or knowledge_base.created_by_user_id == actor.id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Knowledge base owner required.")


async def list_knowledge_bases(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeBaseListItemResponse]:
    rows = await knowledge_base_repository.list_knowledge_base_rows(
        db,
        workspace_id,
        actor.id,
        RESOURCE_TYPE,
        workspace_role == "admin",
        limit,
        offset,
    )
    responses: list[KnowledgeBaseListItemResponse] = []
    for knowledge_base, grant, document_count, char_count in rows:
        permission = effective_permission(
            knowledge_base,
            actor,
            workspace_role,
            grant,
        )
        responses.append(
            KnowledgeBaseListItemResponse(
                **knowledge_base_to_response(
                    knowledge_base,
                    permission,
                ).model_dump(),
                document_count=document_count,
                char_count=char_count,
            )
        )
    return responses


async def get_knowledge_base(
    db: AsyncSession,
    workspace_id: str,
    knowledge_base_id: str,
) -> KnowledgeBase:
    knowledge_base = await knowledge_base_repository.get_knowledge_base_by_id(
        db,
        knowledge_base_id,
    )
    if knowledge_base is None or knowledge_base.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    return knowledge_base


async def create_knowledge_base(
    db: AsyncSession,
    workspace_id: str,
    payload: KnowledgeBaseCreateRequest,
    actor: User,
) -> KnowledgeBaseResponse:
    embedding_model = await get_knowledge_model(
        db,
        workspace_id,
        payload.embedding_model_id,
        "EMBEDDING",
        use_default=True,
    )
    reranker_model = await get_knowledge_model(
        db,
        workspace_id,
        payload.reranker_model_id,
        "RERANKER",
    )
    knowledge_base = KnowledgeBase(
        workspace_id=workspace_id,
        name=normalize_name(payload.name),
        description=payload.description.strip(),
        status=ACTIVE_STATUS,
        embedding_model_id=embedding_model.id if embedding_model else None,
        reranker_model_id=reranker_model.id if reranker_model else None,
        created_by_user_id=actor.id,
    )

    try:
        knowledge_base = await knowledge_base_repository.create_knowledge_base(
            db,
            knowledge_base,
        )
        record_audit_log(
            db,
            actor,
            "knowledge_base.create",
            RESOURCE_TYPE,
            knowledge_base.id,
            knowledge_base.name,
            {"workspace_id": workspace_id},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge base name already exists.") from exc

    knowledge_base = await knowledge_base_repository.refresh_knowledge_base(
        db,
        knowledge_base,
    )
    return knowledge_base_to_response(knowledge_base, "edit")


async def update_knowledge_base(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeBaseUpdateRequest,
    actor: User,
    workspace_role: str | None,
) -> KnowledgeBaseResponse:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")

    details = payload.model_dump(exclude_unset=True)
    if knowledge_base.status == ARCHIVED_STATUS:
        if details != {"status": ACTIVE_STATUS}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Knowledge base is archived.")
        require_can_manage_permissions(knowledge_base, actor, workspace_role)
    else:
        await require_knowledge_base_permission(
            db,
            knowledge_base,
            actor,
            workspace_role,
            {"edit"},
        )

    if payload.name is not None:
        knowledge_base.name = normalize_name(payload.name)
    if payload.description is not None:
        knowledge_base.description = payload.description.strip()
    if payload.status is not None:
        if payload.status not in KNOWLEDGE_BASE_STATUSES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid knowledge base status.")
        knowledge_base.status = payload.status
    if "embedding_model_id" in details:
        embedding_model = await get_knowledge_model(
            db,
            knowledge_base.workspace_id,
            payload.embedding_model_id,
            "EMBEDDING",
        )
        knowledge_base.embedding_model_id = embedding_model.id if embedding_model else None
    if "reranker_model_id" in details:
        reranker_model = await get_knowledge_model(
            db,
            knowledge_base.workspace_id,
            payload.reranker_model_id,
            "RERANKER",
        )
        knowledge_base.reranker_model_id = reranker_model.id if reranker_model else None

    try:
        await knowledge_base_repository.save_knowledge_base(db, knowledge_base)
        record_audit_log(
            db,
            actor,
            "knowledge_base.update",
            RESOURCE_TYPE,
            knowledge_base.id,
            knowledge_base.name,
            details,
            workspace_id=knowledge_base.workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge base name already exists.") from exc

    knowledge_base = await knowledge_base_repository.refresh_knowledge_base(
        db,
        knowledge_base,
    )
    return knowledge_base_to_response(knowledge_base, "edit")


def run_knowledge_model_test(
    embedding_model: RegisteredModel,
    reranker_model: RegisteredModel | None,
    payload: KnowledgeModelTestRequest,
    settings: Settings,
) -> KnowledgeModelTestResponse:
    try:
        embedding = build_embeddings(
            settings,
            embedding_model,
        ).embed_query(payload.query)
        reranker_results = []
        if reranker_model is not None:
            reranker_results = build_reranker(
                settings,
                reranker_model,
            ).rerank(payload.query, payload.documents)
    except ModelProviderStatusError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Knowledge model test failed with provider status {exc.status_code}.",
        ) from exc
    except ModelProviderError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Knowledge model test request failed.",
        ) from exc

    return KnowledgeModelTestResponse(
        embedding_model_id=embedding_model.id,
        embedding_dimensions=len(embedding),
        reranker_model_id=reranker_model.id if reranker_model else None,
        reranker_results=len(reranker_results),
    )


async def test_knowledge_base_models(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeModelTestRequest,
    settings: Settings,
) -> KnowledgeModelTestResponse:
    embedding_model = await get_knowledge_model(
        db,
        knowledge_base.workspace_id,
        knowledge_base.embedding_model_id,
        "EMBEDDING",
        use_default=True,
    )
    if embedding_model is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Embedding model is required.",
        )
    reranker_model = await get_knowledge_model(
        db,
        knowledge_base.workspace_id,
        knowledge_base.reranker_model_id,
        "RERANKER",
    )
    return await asyncio.to_thread(
        run_knowledge_model_test,
        embedding_model,
        reranker_model,
        payload,
        settings,
    )


async def delete_knowledge_base_permanently(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    workspace_role: str | None,
) -> str:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
    require_can_manage_permissions(knowledge_base, actor, workspace_role)
    if await knowledge_base_repository.get_open_knowledge_base_task(db, knowledge_base) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge task is already running.")

    record_audit_log(
        db,
        actor,
        "knowledge_base.delete",
        RESOURCE_TYPE,
        knowledge_base.id,
        knowledge_base.name,
        {"workspace_id": knowledge_base.workspace_id},
        workspace_id=knowledge_base.workspace_id,
    )
    cleanup_id = await create_knowledge_storage_cleanup(db, knowledge_base)
    await knowledge_base_repository.delete_knowledge_base_graph(
        db,
        knowledge_base,
        RESOURCE_TYPE,
    )
    await db.commit()
    return cleanup_id


async def transfer_knowledge_base_owner(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_user_id: str,
    actor: User,
    workspace_role: str | None,
) -> KnowledgeBaseResponse:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_can_manage_permissions(knowledge_base, actor, workspace_role)
    if knowledge_base.status != ACTIVE_STATUS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Knowledge base is archived.")

    target = await permission_repository.get_active_workspace_member(
        db,
        knowledge_base.workspace_id,
        target_user_id,
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")

    previous_owner_id = knowledge_base.created_by_user_id
    knowledge_base.created_by_user_id = target.id
    await knowledge_base_repository.save_knowledge_base(db, knowledge_base)
    record_audit_log(
        db,
        actor,
        "knowledge_base.owner_transfer",
        RESOURCE_TYPE,
        knowledge_base.id,
        knowledge_base.name,
        {
            "previous_owner_user_id": previous_owner_id,
            "new_owner_user_id": target.id,
        },
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    knowledge_base = await knowledge_base_repository.refresh_knowledge_base(
        db,
        knowledge_base,
    )
    permission = effective_permission(
        knowledge_base,
        actor,
        workspace_role,
        await get_user_grant(db, knowledge_base, actor.id),
    )
    return knowledge_base_to_response(knowledge_base, permission)
