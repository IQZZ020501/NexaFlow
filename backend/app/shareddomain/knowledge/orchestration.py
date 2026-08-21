import asyncio
from dataclasses import dataclass
from datetime import UTC, timedelta
import hashlib
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.shareddomain.audit.services import record_audit_log
from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.logger import get_logger
from app.infrastructure.model_utils import new_id, utc_now
from app.entities.user import User
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.infrastructure.repositories import knowledge_graph as graph_repository
from app.entities.knowledge import (
    CHUNK_INDEX_FAILED_STATUS,
    CHUNK_INDEXED_STATUS,
    CHUNK_PREVIEW_STATUS,
    DOCUMENT_DELETED_STATUS,
    DOCUMENT_INDEX_FAILED_STATUS,
    DOCUMENT_INDEX_QUEUED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    DOCUMENT_INDEXING_STATUS,
    DOCUMENT_PARSE_FAILED_STATUS,
    DOCUMENT_PARSE_QUEUED_STATUS,
    DOCUMENT_PARSED_STATUS,
    DOCUMENT_PARSING_STATUS,
    DOCUMENT_STAGED_META_KEY,
    GRAPH_RESUME_REVISION_ID_OPTION,
    GRAPH_RETRY_ALL,
    GRAPH_RETRY_MODE_OPTION,
    GRAPH_RETRY_UNFINISHED,
    TASK_CANCELLED_STATUS,
    TASK_CANCELLING_STATUS,
    TASK_FAILED_STATUS,
    TASK_EVALUATE,
    TASK_GRAPH_REBUILD,
    TASK_GRAPH_SYNC,
    TASK_INDEX,
    TASK_PARSE,
    TASK_QUEUED_STATUS,
    TASK_REBUILD_INDEX,
    TASK_RUNNING_STATUS,
    TASK_SUCCEEDED_STATUS,
    KnowledgeAsset,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentChunk,
    KnowledgeDocumentParentChunk,
    KnowledgeTask,
)
from app.entities.knowledge_graph import GRAPH_REVISION_FAILED
from app.ports.parsing import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    ChildChunkDraft,
    DocumentChunkDrafts,
    KnowledgePipelineError,
    NORMALIZED_TEXT_VERSION,
    SPLIT_SEPARATORS,
    build_flat_chunks,
    build_hierarchical_chunks,
    chunk_token_count,
    clean_text,
    extract_document,
    extract_qa_rows,
    split_text,
)
from app.ports.vector_store import delete_vectors
from app.schemas.knowledge import (
    KnowledgeAssetResponse,
    KnowledgeDocumentChunkResponse,
    KnowledgeDocumentParseRequest,
    KnowledgeTaskResponse,
)
from app.shareddomain.knowledge.permissions import require_knowledge_base_active
from app.shareddomain.knowledge.references import (
    prepare_document_reference_rebuild,
    rebuild_document_references,
)
from app.shareddomain.knowledge.services import (
    get_knowledge_model,
    knowledge_document_path,
    knowledge_object_storage,
)
from app.ports.llm import RegisteredModel

logger = get_logger(__name__)

MAX_TASK_ATTEMPTS = 3
ALLOWED_CLEANING_RULES = {"trim_lines", "collapse_spaces", "remove_empty_lines"}
DEFAULT_PARSE_OPTIONS: dict[str, Any] = {
    "strategy": "flat",
    "chunk_size": CHUNK_SIZE,
    "chunk_overlap": CHUNK_OVERLAP,
    "split_separator": "\n\n",
    "cleaning_rules": [],
    "auto_index": True,
}


@dataclass(frozen=True)
class NormalizedDocumentArtifact:
    object_key: str
    content_hash: str
    content: str


def normalized_document_artifact(
    *,
    workspace_id: str,
    knowledge_base_id: str,
    document_id: str,
    text: str,
) -> NormalizedDocumentArtifact:
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return NormalizedDocumentArtifact(
        object_key=(
            f"{workspace_id}/{knowledge_base_id}/normalized/"
            f"{document_id}/{content_hash}.md"
        ),
        content_hash=content_hash,
        content=text,
    )


def chunk_search_text(
    document: KnowledgeDocument,
    parent: KnowledgeDocumentParentChunk | None,
    chunk: KnowledgeDocumentChunk,
) -> str:
    if chunk.kind == "qa":
        question = (chunk.meta or {}).get("question")
        parts = [question if isinstance(question, str) else "", chunk.content]
    else:
        path = (parent.meta or {}).get("section_path") if parent else None
        section_path = (
            [value for value in path if isinstance(value, str) and value]
            if isinstance(path, list)
            else []
        )
        if not section_path and parent and parent.title:
            section_path = [parent.title]
        parts = [document.filename, *section_path, chunk.content]
    return "\n".join(part for part in parts if part)


def asset_to_response(asset: KnowledgeAsset) -> KnowledgeAssetResponse:
    return KnowledgeAssetResponse(
        id=asset.id,
        kind="image",
        filename=asset.filename,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        alt_text=asset.alt_text,
    )


def chunk_to_response(
    chunk: KnowledgeDocumentChunk,
    parent: KnowledgeDocumentParentChunk | None = None,
    assets: list[KnowledgeAsset] | None = None,
) -> KnowledgeDocumentChunkResponse:
    return KnowledgeDocumentChunkResponse(
        id=chunk.id,
        workspace_id=chunk.workspace_id,
        knowledge_base_id=chunk.knowledge_base_id,
        document_id=chunk.document_id,
        parent_id=chunk.parent_id,
        parent_title=parent.title if parent else None,
        parent_index=parent.parent_index if parent else None,
        chunk_index=chunk.chunk_index,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        content=chunk.content,
        kind=chunk.kind,
        question=(
            (chunk.meta or {}).get("question")
            if isinstance((chunk.meta or {}).get("question"), str)
            else None
        ),
        source=(
            (chunk.meta or {}).get("source") or None
            if isinstance((chunk.meta or {}).get("source"), str)
            else None
        ),
        row_number=(
            (chunk.meta or {}).get("row_number")
            if isinstance((chunk.meta or {}).get("row_number"), int)
            else None
        ),
        char_count=chunk.char_count,
        token_count=chunk.token_count,
        vector_id=chunk.vector_id,
        status=chunk.status,
        images=[asset_to_response(asset) for asset in assets or []],
        created_at=chunk.created_at,
        updated_at=chunk.updated_at,
    )


def task_to_response(task: KnowledgeTask) -> KnowledgeTaskResponse:
    return KnowledgeTaskResponse(
        id=task.id,
        workspace_id=task.workspace_id,
        knowledge_base_id=task.knowledge_base_id,
        document_id=task.document_id,
        task_type=task.task_type,
        status=task.status,
        attempts=task.attempts,
        max_attempts=task.max_attempts,
        total_items=task.total_items,
        processed_items=task.processed_items,
        last_error=task.last_error,
        created_by_user_id=task.created_by_user_id,
        started_at=task.started_at,
        finished_at=task.finished_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


async def get_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document_id: str,
) -> KnowledgeDocument:
    document = await knowledge_base_repository.get_knowledge_document_by_id(db, document_id)
    if (
        document is None
        or document.workspace_id != knowledge_base.workspace_id
        or document.knowledge_base_id != knowledge_base.id
        or document.status == DOCUMENT_DELETED_STATUS
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge document not found.")
    return document


async def list_knowledge_document_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeDocumentChunkResponse]:
    chunks = await knowledge_base_repository.list_document_chunks(
        db,
        knowledge_base,
        document.id,
        limit,
        offset,
    )
    parents = await knowledge_base_repository.list_parent_chunks_by_ids(
        db,
        knowledge_base,
        {chunk.parent_id for chunk in chunks if chunk.parent_id},
    )
    parents_by_id = {parent.id: parent for parent in parents}
    asset_rows = await knowledge_base_repository.list_chunk_assets(
        db,
        knowledge_base,
        {chunk.id for chunk in chunks},
    )
    assets_by_chunk: dict[str, list[KnowledgeAsset]] = {}
    for chunk_asset, asset in asset_rows:
        assets_by_chunk.setdefault(chunk_asset.chunk_id, []).append(asset)
    return [
        chunk_to_response(
            chunk,
            parents_by_id.get(chunk.parent_id),
            assets_by_chunk.get(chunk.id, []),
        )
        for chunk in chunks
    ]


async def list_knowledge_tasks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[KnowledgeTaskResponse]:
    tasks = await knowledge_base_repository.list_knowledge_tasks(
        db,
        knowledge_base,
        document.id if document else None,
        limit,
        offset,
    )
    return [task_to_response(task) for task in tasks]


def task_error_message(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    message = detail if isinstance(detail, str) else str(exc)
    return (message or exc.__class__.__name__)[:2000]


def parse_task_options(payload: KnowledgeDocumentParseRequest | None = None) -> dict[str, Any]:
    options = {**DEFAULT_PARSE_OPTIONS, **(payload.model_dump() if payload else {})}
    if options["chunk_overlap"] >= options["chunk_size"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Chunk overlap must be smaller than chunk size.")
    if options["split_separator"] not in SPLIT_SEPARATORS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported split separator.")

    cleaning_rules = list(dict.fromkeys(options["cleaning_rules"]))
    unknown_rules = set(cleaning_rules) - ALLOWED_CLEANING_RULES
    if unknown_rules:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported cleaning rule.")

    options["cleaning_rules"] = cleaning_rules
    return options


def parse_task_options_from_task(task: KnowledgeTask) -> dict[str, Any]:
    return parse_task_options(KnowledgeDocumentParseRequest(**{**DEFAULT_PARSE_OPTIONS, **task.options}))


async def resolve_embedding_model(db: AsyncSession, knowledge_base: KnowledgeBase) -> RegisteredModel | None:
    embedding_model = await get_knowledge_model(
        db,
        knowledge_base.workspace_id,
        knowledge_base.embedding_model_id,
        "EMBEDDING",
        use_default=True,
    )
    if embedding_model is not None and knowledge_base.embedding_model_id is None:
        knowledge_base.embedding_model_id = embedding_model.id
    return embedding_model


async def extract_document_chunk_contents(
    document: KnowledgeDocument,
    settings: Settings,
    options: dict[str, Any],
) -> DocumentChunkDrafts:
    if (document.meta or {}).get("import_mode") == "qa":
        rows = await asyncio.to_thread(
            extract_qa_rows,
            document.filename,
            knowledge_document_path(settings, document.storage_path),
        )
        return DocumentChunkDrafts(
            parents=[],
            children=[
                ChildChunkDraft(
                    content=row.answer,
                    kind="qa",
                    meta={
                        "question": row.question,
                        "source": row.source,
                        "row_number": row.row_number,
                    },
                )
                for row in rows
            ],
        )

    text, assets = await asyncio.to_thread(
        extract_document,
        document.filename,
        document.content_type,
        knowledge_document_path(settings, document.storage_path),
    )
    text = clean_text(
        text,
        options["cleaning_rules"],
        preserve_empty_lines=options["split_separator"] == "\n\n",
    )
    chunks = (
        build_hierarchical_chunks(
            text,
            options["chunk_size"],
            options["chunk_overlap"],
            options["split_separator"],
        )
        if options["strategy"] == "hierarchical"
        else build_flat_chunks(
            split_text(
                text,
                options["chunk_size"],
                options["chunk_overlap"],
                options["split_separator"],
            )
        )
    )
    if not chunks.children:
        raise KnowledgePipelineError("Document has no extractable chunks.")
    return DocumentChunkDrafts(
        parents=chunks.parents,
        children=chunks.children,
        assets=assets,
        normalized_text=text,
    )


async def replace_document_chunks(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    chunks: DocumentChunkDrafts,
    settings: Settings,
) -> tuple[list[str], list[str], list[str]]:
    existing_chunks = await knowledge_base_repository.list_document_chunks(
        db,
        knowledge_base,
        document.id,
    )
    vector_ids = [chunk.vector_id for chunk in existing_chunks if chunk.vector_id]
    await prepare_document_reference_rebuild(
        db,
        knowledge_base,
        document.id,
    )
    stale_object_keys = await knowledge_base_repository.delete_document_assets(
        db,
        document.id,
    )
    await knowledge_base_repository.delete_document_chunks(db, document.id)

    storage = knowledge_object_storage(settings)
    written_object_keys: list[str] = []
    assets: list[KnowledgeAsset] = []
    parents: list[KnowledgeDocumentParentChunk] = []
    children: list[KnowledgeDocumentChunk] = []
    chunk_asset_links: list[tuple[str, str, int]] = []
    try:
        if chunks.normalized_text:
            artifact = normalized_document_artifact(
                workspace_id=document.workspace_id,
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                text=chunks.normalized_text,
            )
            previous_key = str(
                (document.meta or {}).get("normalized_artifact_key") or ""
            )
            if artifact.object_key != previous_key or not storage.path(
                artifact.object_key
            ).exists():
                storage.put_bytes(
                    artifact.object_key,
                    artifact.content.encode("utf-8"),
                )
                written_object_keys.append(artifact.object_key)
            if previous_key and previous_key != artifact.object_key:
                stale_object_keys.append(previous_key)
            document.meta = {
                **(document.meta or {}),
                "normalized_artifact_key": artifact.object_key,
                "normalized_content_hash": artifact.content_hash,
                "normalized_text_version": NORMALIZED_TEXT_VERSION,
                "document_version": int(
                    (document.meta or {}).get("document_version") or 0
                )
                + 1,
            }

        for index, draft in enumerate(chunks.assets):
            object_key = (
                f"{document.workspace_id}/{document.knowledge_base_id}/assets/"
                f"{document.id}/{draft.id}/{draft.filename}"
            )
            storage.put_bytes(object_key, draft.content)
            written_object_keys.append(object_key)
            assets.append(
                KnowledgeAsset(
                    id=draft.id,
                    workspace_id=document.workspace_id,
                    knowledge_base_id=document.knowledge_base_id,
                    document_id=document.id,
                    asset_index=index,
                    kind="image",
                    filename=draft.filename,
                    content_type=draft.content_type,
                    size_bytes=len(draft.content),
                    object_key=object_key,
                    alt_text=draft.alt_text,
                    meta={},
                )
            )

        for index, draft in enumerate(chunks.parents):
            parents.append(
                KnowledgeDocumentParentChunk(
                    id=new_id(),
                    workspace_id=document.workspace_id,
                    knowledge_base_id=document.knowledge_base_id,
                    document_id=document.id,
                    parent_index=index,
                    title=draft.title,
                    content=draft.content,
                    char_count=len(draft.content),
                    meta={"section_path": draft.section_path},
                )
            )

        for index, draft in enumerate(chunks.children):
            parent = (
                parents[draft.parent_index]
                if draft.parent_index is not None
                else None
            )
            if parent is not None and (
                draft.start_offset is None
                or draft.end_offset is None
                or (
                    parent.content[draft.start_offset : draft.end_offset]
                    != draft.content
                    and not draft.content.endswith(
                        parent.content[draft.start_offset : draft.end_offset]
                    )
                )
            ):
                raise KnowledgePipelineError("Knowledge chunk offsets are invalid.")
            chunk = KnowledgeDocumentChunk(
                id=new_id(),
                workspace_id=document.workspace_id,
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                parent_id=parent.id if parent else None,
                chunk_index=index,
                start_offset=draft.start_offset,
                end_offset=draft.end_offset,
                content=draft.content,
                kind=draft.kind,
                meta=draft.meta,
                char_count=len(draft.content),
                token_count=chunk_token_count(draft.content),
                status=CHUNK_PREVIEW_STATUS,
            )
            chunk.search_text = chunk_search_text(document, parent, chunk)
            children.append(chunk)
            for asset_index, document_asset_index in enumerate(
                draft.asset_indexes
            ):
                if not 0 <= document_asset_index < len(chunks.assets):
                    continue
                chunk_asset_links.append(
                    (
                        chunk.id,
                        chunks.assets[document_asset_index].id,
                        asset_index,
                    )
                )

        await knowledge_base_repository.replace_document_chunks(
            db,
            knowledge_base,
            document.id,
            parents,
            children,
            assets,
            chunk_asset_links,
        )
        await rebuild_document_references(
            db,
            knowledge_base,
            document,
            children,
        )
    except Exception:
        for object_key in written_object_keys:
            storage.delete(object_key)
        raise
    return vector_ids, stale_object_keys, written_object_keys


async def create_knowledge_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument | None,
    task_type: str,
    actor: User,
    options: dict[str, Any] | None = None,
) -> KnowledgeTaskResponse:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
    document_id = document.id if document else None
    task_options = options or {}
    conflict = await get_conflicting_open_task(
        db,
        knowledge_base,
        task_type,
        document_id,
    )
    follows_running_graph = (
        conflict is not None
        and task_type == TASK_GRAPH_REBUILD
        and conflict.task_type in {TASK_GRAPH_SYNC, TASK_GRAPH_REBUILD}
        and conflict.status == TASK_RUNNING_STATUS
        and task_options.get("follower_of_task_id") == conflict.id
    )
    if conflict is not None and not follows_running_graph:
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge task is already running.")
    if (
        task_type == TASK_INDEX
        and document is not None
        and (document.meta or {}).get("import_mode") == "graph"
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Graph import documents do not use the chunk vector index.",
        )

    if task_type in {TASK_INDEX, TASK_REBUILD_INDEX}:
        had_embedding_model = knowledge_base.embedding_model_id is not None
        embedding_model = await resolve_embedding_model(db, knowledge_base)
        if embedding_model is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Embedding model is required.",
            )
        if not had_embedding_model:
            await knowledge_base_repository.set_knowledge_base_embedding_model_id(
                db,
                knowledge_base.id,
                embedding_model.id,
            )

    total_items = 0
    if task_type == TASK_INDEX and document is not None:
        chunks = await knowledge_base_repository.list_document_chunks(db, knowledge_base, document.id)
        if not chunks:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Document has no preview chunks.")
        total_items = len(chunks)
        document.status = DOCUMENT_INDEX_QUEUED_STATUS
        document.meta = {
            **(document.meta or {}),
            DOCUMENT_STAGED_META_KEY: False,
        }
        document.last_error = None
    elif task_type == TASK_PARSE and document is not None:
        document.status = DOCUMENT_PARSE_QUEUED_STATUS
        document.last_error = None
    elif task_type == TASK_REBUILD_INDEX:
        chunks = [
            chunk
            for chunk in await knowledge_base_repository.list_indexable_chunks(
                db,
                knowledge_base,
                statuses={CHUNK_INDEXED_STATUS},
            )
            if chunk.kind != "graph_record"
        ]
        if not chunks:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Knowledge base has no indexed chunks.")
        total_items = len(chunks)
    elif task_type == TASK_EVALUATE:
        total_items = len(task_options.get("case_ids", []))
        if total_items == 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Evaluation task has no cases.",
            )
    elif task_type == TASK_GRAPH_SYNC:
        if not knowledge_base.graph_enabled:
            raise HTTPException(status.HTTP_409_CONFLICT, "Graph RAG is disabled.")
        changed_document_ids = list(
            dict.fromkeys(
                str(item)
                for item in task_options.get("changed_document_ids", [])
                if str(item)
            )
        )
        if not changed_document_ids and not isinstance(
            task_options.get("review_decision"),
            dict,
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Graph sync requires changed documents.",
            )
        if document is not None and document.status != DOCUMENT_INDEXED_STATUS:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Document must be indexed before graph sync.",
            )
        total_items = len(
            await knowledge_base_repository.list_chunks_for_documents(
                db,
                knowledge_base,
                set(changed_document_ids),
            )
        )
        task_options = {
            **task_options,
            "changed_document_ids": changed_document_ids,
        }
    elif task_type == TASK_GRAPH_REBUILD:
        if not knowledge_base.graph_enabled:
            raise HTTPException(status.HTTP_409_CONFLICT, "Graph RAG is disabled.")
        chunks = await knowledge_base_repository.list_indexable_chunks(
            db,
            knowledge_base,
            statuses={CHUNK_INDEXED_STATUS},
        )
        if not chunks and knowledge_base.active_graph_revision_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Knowledge base has no indexed chunks.",
            )
        total_items = len(chunks)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid knowledge task.")

    if document is not None:
        await knowledge_base_repository.save_knowledge_document(db, document)

    task = KnowledgeTask(
        id=new_id(),
        workspace_id=knowledge_base.workspace_id,
        knowledge_base_id=knowledge_base.id,
        document_id=document_id,
        task_type=task_type,
        status=TASK_QUEUED_STATUS,
        attempts=0,
        max_attempts=MAX_TASK_ATTEMPTS,
        total_items=total_items,
        processed_items=0,
        options=task_options,
        created_by_user_id=actor.id,
    )
    task = await knowledge_base_repository.create_knowledge_task(db, task)
    record_audit_log(
        db,
        actor,
        f"knowledge_task.{task_type}.queue",
        "knowledge_task",
        task.id,
        task_type,
        {"knowledge_base_id": knowledge_base.id, "document_id": document_id},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    task = await knowledge_base_repository.refresh_knowledge_task(db, task)
    return task_to_response(task)


async def get_conflicting_open_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_type: str,
    document_id: str | None,
) -> KnowledgeTask | None:
    if task_type in {TASK_REBUILD_INDEX, TASK_EVALUATE, TASK_GRAPH_REBUILD}:
        return await knowledge_base_repository.get_open_knowledge_base_task(db, knowledge_base)
    if task_type == TASK_GRAPH_SYNC:
        queued_graph = await knowledge_base_repository.get_queued_graph_sync(
            db,
            knowledge_base,
        ) or await knowledge_base_repository.get_queued_graph_rebuild(
            db,
            knowledge_base,
        )
        if queued_graph is not None:
            return queued_graph
        for blocking_task_type in (TASK_REBUILD_INDEX, TASK_EVALUATE):
            blocking_task = await knowledge_base_repository.get_open_knowledge_task(
                db,
                knowledge_base,
                blocking_task_type,
                None,
            )
            if blocking_task is not None:
                return blocking_task
        return None
    if document_id is None:
        return await knowledge_base_repository.get_open_knowledge_task(
            db,
            knowledge_base,
            task_type,
            document_id,
        )
    open_task = await knowledge_base_repository.get_open_document_task(
        db,
        knowledge_base,
        document_id,
    )
    if open_task is not None:
        return open_task
    for blocking_task_type in (
        TASK_REBUILD_INDEX,
        TASK_EVALUATE,
        TASK_GRAPH_REBUILD,
    ):
        blocking_task = await knowledge_base_repository.get_open_knowledge_task(
            db,
            knowledge_base,
            blocking_task_type,
            None,
        )
        if blocking_task is not None:
            return blocking_task
    return None


async def enqueue_graph_sync(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    changed_document_ids: list[str],
    *,
    options: dict[str, Any] | None = None,
) -> KnowledgeTask:
    locked = await knowledge_base_repository.lock_knowledge_base(db, knowledge_base)
    if locked is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    queued = await knowledge_base_repository.get_queued_graph_sync(db, locked)
    if queued is not None:
        queued_options = queued.options or {}
        incoming_options = options or {}
        queued.options = {
            **queued_options,
            **incoming_options,
            "changed_document_ids": sorted(
                {
                    *queued_options.get("changed_document_ids", []),
                    *changed_document_ids,
                }
            ),
        }
        structured_document_ids = {
            *queued_options.get("structured_document_ids", []),
            *incoming_options.get("structured_document_ids", []),
        }
        if structured_document_ids:
            queued.options["structured_document_ids"] = sorted(
                structured_document_ids
            )
        await knowledge_base_repository.save_knowledge_task(db, queued)
        await db.commit()
        return await knowledge_base_repository.refresh_knowledge_task(db, queued)
    queued_rebuild = await knowledge_base_repository.get_queued_graph_rebuild(
        db,
        locked,
    )
    if queued_rebuild is not None:
        return queued_rebuild
    response = await create_knowledge_task(
        db,
        locked,
        None,
        TASK_GRAPH_SYNC,
        actor,
        options={
            **(options or {}),
            "changed_document_ids": sorted(set(changed_document_ids)),
        },
    )
    task = await knowledge_base_repository.get_knowledge_task_by_id(db, response.id)
    assert task is not None
    return task


async def enqueue_graph_rebuild(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
    *,
    follow_running: bool = True,
) -> KnowledgeTask:
    locked = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if locked is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    queued = await knowledge_base_repository.get_queued_graph_rebuild(
        db,
        locked,
    )
    queued_sync = await knowledge_base_repository.get_queued_graph_sync(db, locked)
    if queued is not None:
        if queued_sync is not None:
            queued_sync.status = TASK_SUCCEEDED_STATUS
            queued_sync.last_error = f"Coalesced into graph rebuild {queued.id}."
            queued_sync.finished_at = utc_now()
            await knowledge_base_repository.save_knowledge_task(db, queued_sync)
            await db.commit()
        return queued
    running = await knowledge_base_repository.get_running_graph_task(db, locked)
    if running is not None and not follow_running and running.task_type == TASK_GRAPH_REBUILD:
        return running
    if queued_sync is not None:
        queued_sync.status = TASK_SUCCEEDED_STATUS
        queued_sync.last_error = "Coalesced into graph rebuild."
        queued_sync.finished_at = utc_now()
        await knowledge_base_repository.save_knowledge_task(db, queued_sync)
    response = await create_knowledge_task(
        db,
        locked,
        None,
        TASK_GRAPH_REBUILD,
        actor,
        options=(
            {"follower_of_task_id": running.id}
            if running is not None
            else {}
        ),
    )
    task = await knowledge_base_repository.get_knowledge_task_by_id(db, response.id)
    assert task is not None
    if queued_sync is not None:
        queued_sync.last_error = f"Coalesced into graph rebuild {task.id}."
        await knowledge_base_repository.save_knowledge_task(db, queued_sync)
        await db.commit()
    return task


async def enqueue_parse_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: User,
    payload: KnowledgeDocumentParseRequest | None = None,
) -> KnowledgeTaskResponse:
    return await create_knowledge_task(
        db,
        knowledge_base,
        document,
        TASK_PARSE,
        actor,
        parse_task_options(payload),
    )


async def enqueue_index_knowledge_document(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: User,
) -> KnowledgeTaskResponse:
    if document.status not in {
        DOCUMENT_PARSED_STATUS,
        DOCUMENT_INDEXED_STATUS,
        DOCUMENT_INDEX_FAILED_STATUS,
    }:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Document preview must be generated before indexing.",
        )
    return await create_knowledge_task(db, knowledge_base, document, TASK_INDEX, actor)


async def enqueue_rebuild_knowledge_index(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    actor: User,
) -> KnowledgeTaskResponse:
    return await create_knowledge_task(db, knowledge_base, None, TASK_REBUILD_INDEX, actor)


async def retry_knowledge_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
    actor: User,
    retry_mode: str = GRAPH_RETRY_ALL,
) -> KnowledgeTaskResponse:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
    task = await knowledge_base_repository.get_knowledge_task_by_id(db, task_id)
    if task is None or task.workspace_id != knowledge_base.workspace_id or task.knowledge_base_id != knowledge_base.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge task not found.")
    if task.status not in {TASK_FAILED_STATUS, TASK_CANCELLED_STATUS}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only failed or stopped knowledge tasks can be retried.",
        )
    if task.attempts >= task.max_attempts:
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge task retry limit reached.")
    if await get_conflicting_open_task(db, knowledge_base, task.task_type, task.document_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Knowledge task is already running.")

    if retry_mode not in {GRAPH_RETRY_ALL, GRAPH_RETRY_UNFINISHED}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown retry mode.")
    is_graph_task = task.task_type in {TASK_GRAPH_SYNC, TASK_GRAPH_REBUILD}
    if retry_mode == GRAPH_RETRY_UNFINISHED:
        if not is_graph_task:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Only graph tasks can retry unfinished chunks.",
            )
        if not 0 < task.processed_items < task.total_items:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "No unfinished graph chunks are available to retry.",
            )
        revision = await graph_repository.get_latest_revision(db, knowledge_base)
        if (
            revision is None
            or revision.status != GRAPH_REVISION_FAILED
            or str((revision.stats_json or {}).get("task_id") or "") != task.id
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The graph task checkpoint is no longer available; retry all chunks.",
            )
        task.options = {
            **(task.options or {}),
            GRAPH_RETRY_MODE_OPTION: GRAPH_RETRY_UNFINISHED,
            GRAPH_RESUME_REVISION_ID_OPTION: revision.id,
        }
    else:
        options = dict(task.options or {})
        options.pop(GRAPH_RETRY_MODE_OPTION, None)
        options.pop(GRAPH_RESUME_REVISION_ID_OPTION, None)
        task.options = options
        task.processed_items = 0

    if task.document_id is not None:
        document = await get_knowledge_document(db, knowledge_base, task.document_id)
        if task.task_type == TASK_PARSE:
            document.status = DOCUMENT_PARSE_QUEUED_STATUS
        elif task.task_type == TASK_INDEX:
            document.status = DOCUMENT_INDEX_QUEUED_STATUS
            document.meta = {
                **(document.meta or {}),
                DOCUMENT_STAGED_META_KEY: False,
            }
        document.last_error = None
        await knowledge_base_repository.save_knowledge_document(db, document)

    task.status = TASK_QUEUED_STATUS
    task.last_error = None
    task.lease_expires_at = None
    task.worker_task_id = None
    task.finished_at = None
    await knowledge_base_repository.save_knowledge_task(db, task)
    record_audit_log(
        db,
        actor,
        "knowledge_task.retry",
        "knowledge_task",
        task.id,
        task.task_type,
        {
            "knowledge_base_id": knowledge_base.id,
            "document_id": task.document_id,
            "retry_mode": retry_mode,
        },
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    task = await knowledge_base_repository.refresh_knowledge_task(db, task)
    return task_to_response(task)


TASK_STOPPED_MESSAGE = "Knowledge task stopped by user."


async def stop_knowledge_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
    actor: User,
) -> KnowledgeTaskResponse:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
    task = await knowledge_base_repository.lock_knowledge_task(db, task_id)
    if task is None or (
        task.workspace_id != knowledge_base.workspace_id
        or task.knowledge_base_id != knowledge_base.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge task not found.")
    if task.status not in {TASK_QUEUED_STATUS, TASK_RUNNING_STATUS}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only queued or running knowledge tasks can be stopped.",
        )

    was_running = task.status == TASK_RUNNING_STATUS
    task.status = TASK_CANCELLING_STATUS if was_running else TASK_CANCELLED_STATUS
    task.last_error = TASK_STOPPED_MESSAGE
    if not was_running:
        task.lease_expires_at = None
        task.worker_task_id = None
        task.finished_at = utc_now()
    else:
        cancellation_deadline = utc_now() + timedelta(seconds=60)
        current_lease = task.lease_expires_at
        if current_lease is not None and current_lease.tzinfo is None:
            current_lease = current_lease.replace(tzinfo=UTC)
        task.lease_expires_at = min(
            current_lease or cancellation_deadline,
            cancellation_deadline,
        )
    if task.document_id is not None:
        document = await get_knowledge_document(db, knowledge_base, task.document_id)
        if task.task_type == TASK_PARSE:
            document.status = DOCUMENT_PARSE_FAILED_STATUS
            document.last_error = TASK_STOPPED_MESSAGE
            await knowledge_base_repository.save_knowledge_document(db, document)
        elif task.task_type in {TASK_INDEX, TASK_REBUILD_INDEX}:
            document.status = DOCUMENT_INDEX_FAILED_STATUS
            document.last_error = TASK_STOPPED_MESSAGE
            await knowledge_base_repository.save_knowledge_document(db, document)
            for chunk in await knowledge_base_repository.list_document_chunks(
                db,
                knowledge_base,
                document.id,
            ):
                chunk.status = CHUNK_INDEX_FAILED_STATUS
                await knowledge_base_repository.save_knowledge_document_chunk(db, chunk)
    await knowledge_base_repository.save_knowledge_task(db, task)
    record_audit_log(
        db,
        actor,
        "knowledge_task.stop",
        "knowledge_task",
        task.id,
        task.task_type,
        {
            "knowledge_base_id": knowledge_base.id,
            "document_id": task.document_id,
            "status": task.status,
        },
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
    task = await knowledge_base_repository.refresh_knowledge_task(db, task)
    return task_to_response(task)


async def delete_knowledge_task(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
    task_id: str,
    actor: User,
) -> None:
    knowledge_base = await knowledge_base_repository.lock_knowledge_base(
        db,
        knowledge_base,
    )
    if knowledge_base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found.")
    require_knowledge_base_active(knowledge_base)
    task = await knowledge_base_repository.lock_knowledge_task(db, task_id)
    if task is None or (
        task.workspace_id != knowledge_base.workspace_id
        or task.knowledge_base_id != knowledge_base.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge task not found.")
    if task.status in {
        TASK_QUEUED_STATUS,
        TASK_RUNNING_STATUS,
        TASK_CANCELLING_STATUS,
    }:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Stop the knowledge task before deleting it.",
        )
    await knowledge_base_repository.delete_knowledge_task(db, task)
    record_audit_log(
        db,
        actor,
        "knowledge_task.delete",
        "knowledge_task",
        task.id,
        task.task_type,
        {"knowledge_base_id": knowledge_base.id, "status": task.status},
        workspace_id=knowledge_base.workspace_id,
    )
    await db.commit()
