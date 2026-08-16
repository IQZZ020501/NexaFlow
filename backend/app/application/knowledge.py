"""Knowledge use cases.

Single facade consumed by the knowledge API endpoints: CRUD, document
lifecycle, task dispatch, retrieval orchestration, and object-file access.
Endpoints must not import ``app.shareddomain``, ``app.capabilities``, or
``app.infrastructure`` directly; this module is the only entry point.
"""

from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.knowledge_retrieval import (
    query_knowledge_base,
    retrieve_knowledge_base,
)
from app.application.knowledge_evaluation import (
    get_evaluation_summary,
    get_latest_evaluation_summary,
)
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.schemas.knowledge import KnowledgeDocumentResponse
from app.shareddomain.knowledge.lifecycle import (
    delete_knowledge_document,
    set_knowledge_document_active,
)
from app.shareddomain.knowledge.evaluation import (
    create_evaluation_case,
    delete_evaluation_case,
    delete_evaluation_run,
    enqueue_evaluation_run,
    get_evaluation_run,
    list_evaluation_cases,
    list_evaluation_runs,
)
from app.shareddomain.knowledge.orchestration import (
    enqueue_index_knowledge_document,
    enqueue_parse_knowledge_document,
    enqueue_rebuild_knowledge_index,
    get_knowledge_document,
    list_knowledge_document_chunks,
    list_knowledge_tasks,
    retry_knowledge_task,
)
from app.entities.knowledge import (
    KnowledgeAsset,
    KnowledgeBase,
    KnowledgeDocument,
)
from app.entities.user import User
from app.shareddomain.knowledge.services import (
    create_knowledge_base,
    create_knowledge_documents_from_attachments,
    delete_knowledge_attachment,
    delete_knowledge_base_permanently as delete_knowledge_base_record,
    document_to_response,
    get_knowledge_base,
    knowledge_document_path,
    knowledge_object_storage,
    list_knowledge_bases,
    list_knowledge_documents,
    list_resource_permissions,
    require_can_manage_permissions,
    require_knowledge_base_permission,
    revoke_resource_permission,
    test_knowledge_base_models,
    transfer_knowledge_base_owner,
    update_knowledge_base,
    upload_knowledge_attachment,
    upsert_resource_permission,
)
from app.tasks.knowledge import (
    enqueue_knowledge_storage_cleanup,
    enqueue_knowledge_task,
)

logger = get_logger(__name__)


async def delete_knowledge_base_permanently(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> None:
    cleanup_id = await delete_knowledge_base_record(
        db,
        knowledge_base,
        actor,
        workspace_role,
    )
    await enqueue_knowledge_storage_cleanup(cleanup_id, settings)


async def dispatch_knowledge_task(task_id: str, settings: Settings) -> None:
    try:
        await enqueue_knowledge_task(task_id, settings)
    except Exception as exc:
        log_error(logger, "Knowledge task dispatch failed.", exc, task_id=task_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Knowledge task queue is unavailable.",
        ) from exc


async def list_knowledge_documents_with_counts(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    *,
    include_staged: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeDocumentResponse]:
    documents = await list_knowledge_documents(
        db,
        knowledge_base,
        include_staged=include_staged,
        limit=limit,
        offset=offset,
    )
    chunk_counts = await knowledge_base_repository.count_document_chunks(
        db,
        knowledge_base,
    )
    return [
        document_to_response(document, chunk_count=chunk_counts.get(document.id, 0))
        for document in documents
    ]


async def document_response_with_chunk_count(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
) -> KnowledgeDocumentResponse:
    chunk_counts = await knowledge_base_repository.count_document_chunks(
        db,
        knowledge_base,
    )
    return document_to_response(
        document,
        chunk_count=chunk_counts.get(document.id, 0),
    )


async def get_knowledge_asset_file(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
    asset_id: str,
    settings: Settings,
) -> tuple[KnowledgeAsset, Path]:
    """Resolve a knowledge asset and its on-disk path for HTTP serving."""
    asset = await knowledge_base_repository.get_document_asset(
        db,
        knowledge_base,
        document_id,
        asset_id,
    )
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge asset not found.")
    asset_path = knowledge_object_storage(settings).path(asset.object_key)
    if not asset_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge asset file is missing.")
    return asset, asset_path


__all__ = [
    "create_knowledge_base",
    "create_knowledge_documents_from_attachments",
    "delete_knowledge_attachment",
    "delete_knowledge_base_permanently",
    "delete_knowledge_document",
    "create_evaluation_case",
    "delete_evaluation_case",
    "delete_evaluation_run",
    "dispatch_knowledge_task",
    "document_response_with_chunk_count",
    "document_to_response",
    "enqueue_index_knowledge_document",
    "enqueue_evaluation_run",
    "enqueue_parse_knowledge_document",
    "enqueue_rebuild_knowledge_index",
    "get_knowledge_asset_file",
    "get_evaluation_run",
    "get_evaluation_summary",
    "get_latest_evaluation_summary",
    "get_knowledge_base",
    "get_knowledge_document",
    "knowledge_document_path",
    "list_knowledge_bases",
    "list_evaluation_cases",
    "list_evaluation_runs",
    "list_knowledge_document_chunks",
    "list_knowledge_documents",
    "list_knowledge_documents_with_counts",
    "list_knowledge_tasks",
    "list_resource_permissions",
    "query_knowledge_base",
    "retrieve_knowledge_base",
    "require_can_manage_permissions",
    "require_knowledge_base_permission",
    "retry_knowledge_task",
    "revoke_resource_permission",
    "set_knowledge_document_active",
    "test_knowledge_base_models",
    "transfer_knowledge_base_owner",
    "update_knowledge_base",
    "upload_knowledge_attachment",
    "upsert_resource_permission",
]
