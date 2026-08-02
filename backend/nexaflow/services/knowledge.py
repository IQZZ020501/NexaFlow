import asyncio
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, UploadFile, status

from nexaflow.services.audit import record_audit_log
from nexaflow.core.config import Settings
from nexaflow.core.validation import normalize_name
from nexaflow.db.model_utils import new_id
from nexaflow.models.user import User
from nexaflow.services.auth import user_to_response
from nexaflow.services import knowledge_repositories as knowledge_base_repository
from nexaflow.models.knowledge import KnowledgeBase, KnowledgeDocument
from nexaflow.services.knowledge_pipeline import delete_chroma_collection
from nexaflow.schemas.knowledge import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentResponse,
    KnowledgeModelTestRequest,
    KnowledgeModelTestResponse,
    ResourcePermissionResponse,
)
from nexaflow.services import model_repositories as model_repository
from nexaflow.models.model import RegisteredModel
from nexaflow.llm.runtime import (
    ModelProviderError,
    ModelProviderStatusError,
    build_registered_model_provider,
)
from nexaflow.models.resource_permission import ResourcePermission

RESOURCE_TYPE = "knowledge_base"
ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"
DOCUMENT_UPLOADED_STATUS = "uploaded"
MAX_DOCUMENT_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
KNOWLEDGE_BASE_STATUSES = {ACTIVE_STATUS, ARCHIVED_STATUS}
RESOURCE_PERMISSIONS = {"view", "edit"}
DEFAULT_DOCUMENT_META = {"allow_download": True, "security_level": "PUBLIC"}
RESTRICTED_FILENAME_MARKERS = ("秘密", "机密", "绝密")


def validate_permission(permission: str) -> None:
    if permission not in RESOURCE_PERMISSIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Invalid resource permission.",
        )


def effective_permission(
    knowledge_base: KnowledgeBase,
    user: User,
    workspace_role: str | None,
    grant: ResourcePermission | None = None,
) -> str:
    if workspace_role == "admin" or knowledge_base.created_by_user_id == user.id:
        return "edit"
    if grant is None:
        return "none"
    return grant.permission


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


def document_to_response(
    document: KnowledgeDocument,
    chunk_count: int = 0,
) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse(
        id=document.id,
        workspace_id=document.workspace_id,
        knowledge_base_id=document.knowledge_base_id,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        meta=document.meta,
        status=document.status,
        is_active=document.is_active,
        chunk_count=chunk_count,
        last_error=document.last_error,
        created_by_user_id=document.created_by_user_id,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def clean_upload_filename(filename: str | None) -> str:
    name = Path(filename or "").name.strip()
    if not name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Document filename is required.",
        )
    if any(marker in name for marker in RESTRICTED_FILENAME_MARKERS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Document filename contains restricted classification.",
        )
    return name[:255]


def knowledge_document_path(settings: Settings, storage_path: str) -> Path:
    return settings.knowledge_storage_dir / storage_path


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
) -> list[KnowledgeBaseResponse]:
    rows = await knowledge_base_repository.list_knowledge_base_rows(
        db,
        workspace_id,
        actor.id,
        workspace_role,
        RESOURCE_TYPE,
    )
    return [
        knowledge_base_to_response(
            knowledge_base,
            effective_permission(knowledge_base, actor, workspace_role, permission),
        )
        for knowledge_base, permission in rows
    ]


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


async def get_user_grant(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    user_id: str,
) -> ResourcePermission | None:
    return await knowledge_base_repository.get_user_grant(
        db,
        knowledge_base,
        user_id,
        RESOURCE_TYPE,
    )


async def require_knowledge_base_permission(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    workspace_role: str | None,
    permissions: set[str],
) -> str:
    permission = effective_permission(
        knowledge_base,
        actor,
        workspace_role,
        await get_user_grant(db, knowledge_base, actor.id),
    )
    if permission == "edit" or permission in permissions:
        return permission
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Knowledge base access denied.")


async def list_knowledge_documents(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    include_staged: bool = False,
) -> list[KnowledgeDocumentResponse]:
    return [
        document_to_response(document)
        for document in await knowledge_base_repository.list_knowledge_documents(
            db,
            knowledge_base,
            include_staged=include_staged,
        )
    ]


async def save_upload_file(upload: UploadFile, target_path: Path) -> int:
    size = 0
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target_path.open("wb") as output:
            while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_DOCUMENT_UPLOAD_BYTES:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        "Document is too large.",
                    )
                output.write(chunk)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise

    if size == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Document is empty.")
    return size


async def upload_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    upload: UploadFile,
    actor: User,
    settings: Settings,
    meta: dict[str, Any] | None = None,
) -> KnowledgeDocumentResponse:
    document_id = new_id()
    filename = clean_upload_filename(upload.filename)
    storage_path = f"{knowledge_base.workspace_id}/{knowledge_base.id}/{document_id}/{filename}"
    target_path = knowledge_document_path(settings, storage_path)
    size = await save_upload_file(upload, target_path)
    document = KnowledgeDocument(
        id=document_id,
        workspace_id=knowledge_base.workspace_id,
        knowledge_base_id=knowledge_base.id,
        filename=filename,
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=size,
        storage_path=storage_path,
        meta={**DEFAULT_DOCUMENT_META, **(meta or {})},
        status=DOCUMENT_UPLOADED_STATUS,
        last_error=None,
        created_by_user_id=actor.id,
    )
    db.add(document)
    record_audit_log(
        db,
        actor,
        "knowledge_document.upload",
        "knowledge_document",
        document.id,
        document.filename,
        {
            "workspace_id": knowledge_base.workspace_id,
            "knowledge_base_id": knowledge_base.id,
            "size_bytes": size,
        },
        workspace_id=knowledge_base.workspace_id,
    )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        target_path.unlink(missing_ok=True)
        raise

    await db.refresh(document)
    return document_to_response(document)


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
    db.add(knowledge_base)

    try:
        await db.flush()
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

    await db.refresh(knowledge_base)
    return knowledge_base_to_response(knowledge_base, "edit")


async def update_knowledge_base(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    payload: KnowledgeBaseUpdateRequest,
    actor: User,
) -> KnowledgeBaseResponse:
    details = payload.model_dump(exclude_unset=True)
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

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge base name already exists.") from exc

    await db.refresh(knowledge_base)
    return knowledge_base_to_response(knowledge_base, "edit")


def run_knowledge_model_test(
    embedding_model: RegisteredModel,
    reranker_model: RegisteredModel | None,
    payload: KnowledgeModelTestRequest,
    settings: Settings,
) -> KnowledgeModelTestResponse:
    try:
        embedding = build_registered_model_provider(embedding_model, settings).embed(
            [payload.query]
        )
        reranker_results = []
        if reranker_model is not None:
            reranker_results = build_registered_model_provider(
                reranker_model,
                settings,
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
        embedding_dimensions=len(embedding[0]) if embedding else 0,
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
    settings: Settings,
) -> None:
    require_can_manage_permissions(knowledge_base, actor, workspace_role)
    await knowledge_base_repository.lock_knowledge_base(db, knowledge_base)
    if await knowledge_base_repository.get_open_knowledge_base_task(db, knowledge_base) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge task is already running.")

    storage_dir = settings.knowledge_storage_dir / knowledge_base.workspace_id / knowledge_base.id
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
    await knowledge_base_repository.delete_knowledge_base_graph(
        db,
        knowledge_base,
        RESOURCE_TYPE,
    )
    await db.commit()
    await asyncio.to_thread(delete_chroma_collection, settings, knowledge_base.id)
    shutil.rmtree(storage_dir, ignore_errors=True)


async def list_resource_permissions(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> list[ResourcePermissionResponse]:
    rows = await knowledge_base_repository.list_resource_permission_rows(
        db,
        knowledge_base,
        RESOURCE_TYPE,
    )
    return [
        ResourcePermissionResponse(
            user=user_to_response(user, [], []),
            permission=permission.permission,
        )
        for permission, user in rows
    ]


async def upsert_resource_permission(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_user_id: str,
    permission: str,
    actor: User,
) -> ResourcePermissionResponse:
    validate_permission(permission)
    target = await knowledge_base_repository.get_active_workspace_member(
        db,
        knowledge_base.workspace_id,
        target_user_id,
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")

    resource_permission = await get_user_grant(db, knowledge_base, target_user_id)
    if resource_permission is None:
        resource_permission = ResourcePermission(
            workspace_id=knowledge_base.workspace_id,
            resource_type=RESOURCE_TYPE,
            resource_id=knowledge_base.id,
            user_id=target_user_id,
            permission=permission,
            created_by_user_id=actor.id,
        )
        db.add(resource_permission)
    else:
        resource_permission.permission = permission

    record_audit_log(
        db,
        actor,
        "resource_permission.grant",
        RESOURCE_TYPE,
        knowledge_base.id,
        knowledge_base.name,
        {"user_id": target_user_id, "permission": permission},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    return ResourcePermissionResponse(
        user=user_to_response(target, [], []),
        permission=permission,
    )


async def revoke_resource_permission(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    target_user_id: str,
    actor: User,
) -> None:
    deleted_count = await knowledge_base_repository.delete_resource_permission(
        db,
        knowledge_base,
        target_user_id,
        RESOURCE_TYPE,
    )
    if deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource permission not found.")

    record_audit_log(
        db,
        actor,
        "resource_permission.revoke",
        RESOURCE_TYPE,
        knowledge_base.id,
        knowledge_base.name,
        {"user_id": target_user_id},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
