import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shareddomain.audit.services import record_audit_log
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.session import get_session_factory
from app.domain.user import User
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.shareddomain.knowledge.models import (
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeTask,
)
from app.ai.embedding.pipeline import (
    EMBED_BATCH_SIZE,
    KnowledgePipelineError,
    VectorChunk,
    delete_chroma_vectors,
    upsert_chroma_vectors,
)
from app.shareddomain.knowledge.processing import (
    CHUNK_INDEXED_STATUS,
    CHUNK_INDEX_FAILED_STATUS,
    DOCUMENT_DELETED_STATUS,
    DOCUMENT_INDEXED_STATUS,
    DOCUMENT_INDEXING_STATUS,
    DOCUMENT_INDEX_FAILED_STATUS,
    DOCUMENT_PARSED_STATUS,
    DOCUMENT_PARSING_STATUS,
    DOCUMENT_PARSE_FAILED_STATUS,
    TASK_FAILED_STATUS,
    TASK_INDEX,
    TASK_PARSE,
    TASK_QUEUED_STATUS,
    TASK_REBUILD_INDEX,
    TASK_SUCCEEDED_STATUS,
    enqueue_index_knowledge_document,
    extract_document_chunk_contents,
    parse_task_options_from_task,
    replace_document_chunks,
    resolve_embedding_model,
    task_error_message,
)
from app.shareddomain.knowledge.services import RESOURCE_TYPE
from app.ai.llm.models import RegisteredModel
from app.ai.llm.runtime import build_registered_model_provider

# ponytail: fixed lease window; make it configurable if task recovery needs a different budget.
TASK_LEASE_SECONDS = 300
TASK_LEASE_RENEW_SECONDS = 30
TASK_RUN_BUSY = "busy"
TASK_RUN_FINISHED = "finished"


def batches(items: list[VectorChunk], size: int) -> list[list[VectorChunk]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def store_vector_chunks(
    settings: Settings,
    knowledge_base: KnowledgeBase,
    embedding_model: RegisteredModel,
    chunks: list[VectorChunk],
) -> None:
    provider = build_registered_model_provider(embedding_model, settings)
    chunk_batches = batches(chunks, EMBED_BATCH_SIZE)
    embedding_batches = [provider.embed([chunk.content for chunk in batch]) for batch in chunk_batches]
    for batch, embeddings in zip(chunk_batches, embedding_batches, strict=True):
        upsert_chroma_vectors(settings, knowledge_base, batch, embeddings)


async def get_task_scope(
    db: AsyncSession,
    task: KnowledgeTask,
) -> tuple[KnowledgeBase, User, KnowledgeDocument | None]:
    knowledge_base = await db.get(KnowledgeBase, task.knowledge_base_id)
    actor = await db.get(User, task.created_by_user_id)
    document = await db.get(KnowledgeDocument, task.document_id) if task.document_id else None
    if knowledge_base is None:
        raise KnowledgePipelineError("Knowledge base no longer exists.")
    if actor is None:
        raise KnowledgePipelineError("Task actor no longer exists.")
    if task.document_id is not None and (
        document is None or document.status == DOCUMENT_DELETED_STATUS
    ):
        raise KnowledgePipelineError("Knowledge document no longer exists.")
    return knowledge_base, actor, document


async def run_parse_task(
    db: AsyncSession,
    task: KnowledgeTask,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: User,
    settings: Settings,
    lease_lost: asyncio.Event,
) -> None:
    ensure_knowledge_task_lease(lease_lost)
    document.status = DOCUMENT_PARSING_STATUS
    document.last_error = None
    await db.flush()

    options = parse_task_options_from_task(task)
    chunks = await extract_document_chunk_contents(document, settings, options)
    ensure_knowledge_task_lease(lease_lost)
    vector_ids = await replace_document_chunks(db, knowledge_base, document, chunks)

    task.total_items = len(chunks)
    task.processed_items = len(chunks)
    document.status = DOCUMENT_PARSED_STATUS
    document.last_error = None
    record_audit_log(
        db,
        actor,
        "knowledge_document.parse",
        "knowledge_document",
        document.id,
        document.filename,
        {
            "knowledge_base_id": knowledge_base.id,
            "chunk_count": len(chunks),
            "task_id": task.id,
        },
        workspace_id=knowledge_base.workspace_id,
    )
    ensure_knowledge_task_lease(lease_lost)
    await db.commit()
    ensure_knowledge_task_lease(lease_lost)
    await asyncio.to_thread(
        delete_chroma_vectors,
        settings,
        knowledge_base.id,
        vector_ids,
    )


async def run_index_task(
    db: AsyncSession,
    task: KnowledgeTask,
    knowledge_base: KnowledgeBase,
    document: KnowledgeDocument | None,
    actor: User,
    settings: Settings,
    lease_lost: asyncio.Event,
) -> None:
    ensure_knowledge_task_lease(lease_lost)
    embedding_model = await resolve_embedding_model(db, knowledge_base)
    if embedding_model is None:
        raise KnowledgePipelineError("Embedding model is required.")

    chunks = await knowledge_base_repository.list_indexable_chunks(
        db,
        knowledge_base,
        document.id if document else None,
        {CHUNK_INDEXED_STATUS} if task.task_type == TASK_REBUILD_INDEX else None,
    )
    if not chunks:
        raise KnowledgePipelineError("Knowledge task has no chunks to index.")

    documents: dict[str, KnowledgeDocument] = {}
    for chunk in chunks:
        chunk_document = documents.get(chunk.document_id)
        if chunk_document is None:
            loaded = await db.get(KnowledgeDocument, chunk.document_id)
            if loaded is None or loaded.status == DOCUMENT_DELETED_STATUS:
                raise KnowledgePipelineError("Knowledge chunk document is missing.")
            documents[chunk.document_id] = loaded

    if task.task_type != TASK_REBUILD_INDEX:
        for chunk_document in documents.values():
            chunk_document.status = DOCUMENT_INDEXING_STATUS
            chunk_document.last_error = None
    task.total_items = len(chunks)
    task.processed_items = 0
    ensure_knowledge_task_lease(lease_lost)
    await db.commit()

    vector_chunks = [
        VectorChunk(
            id=chunk.id,
            document_id=chunk.document_id,
            document_filename=documents[chunk.document_id].filename,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
        )
        for chunk in chunks
    ]
    for vector_batch in batches(vector_chunks, EMBED_BATCH_SIZE):
        ensure_knowledge_task_lease(lease_lost)
        await asyncio.to_thread(
            store_vector_chunks,
            settings,
            knowledge_base,
            embedding_model,
            vector_batch,
        )
        ensure_knowledge_task_lease(lease_lost)
        task.processed_items += len(vector_batch)
        await db.commit()

    ensure_knowledge_task_lease(lease_lost)
    for chunk in chunks:
        chunk.status = CHUNK_INDEXED_STATUS
        chunk.vector_id = chunk.id
    if task.task_type != TASK_REBUILD_INDEX:
        for chunk_document in documents.values():
            chunk_document.status = DOCUMENT_INDEXED_STATUS
            chunk_document.last_error = None
    task.processed_items = len(chunks)

    record_audit_log(
        db,
        actor,
        "knowledge_document.index",
        "knowledge_document" if document else RESOURCE_TYPE,
        document.id if document else knowledge_base.id,
        document.filename if document else knowledge_base.name,
        {
            "knowledge_base_id": knowledge_base.id,
            "chunk_count": len(chunks),
            "task_id": task.id,
        },
        workspace_id=knowledge_base.workspace_id,
    )


async def mark_knowledge_task_failed(
    db: AsyncSession,
    task_id: str,
    message: str,
    worker_task_id: str | None = None,
    only_if_queued: bool = False,
) -> None:
    task = await db.scalar(
        select(KnowledgeTask).where(KnowledgeTask.id == task_id).with_for_update()
    )
    if task is None:
        return
    if worker_task_id is not None and task.worker_task_id != worker_task_id:
        return
    if only_if_queued and (
        task.status != TASK_QUEUED_STATUS or task.worker_task_id is not None
    ):
        return

    task.status = TASK_FAILED_STATUS
    task.last_error = message
    task.lease_expires_at = None
    task.worker_task_id = None
    task.finished_at = utc_now()

    if task.document_id is not None:
        document = await db.get(KnowledgeDocument, task.document_id)
        if document is not None and document.status != DOCUMENT_DELETED_STATUS:
            document.last_error = message
            if task.task_type == TASK_PARSE:
                document.status = DOCUMENT_PARSE_FAILED_STATUS
            elif task.task_type == TASK_INDEX:
                document.status = DOCUMENT_INDEX_FAILED_STATUS
                knowledge_base = await db.get(KnowledgeBase, task.knowledge_base_id)
                if knowledge_base is not None:
                    chunks = await knowledge_base_repository.list_document_chunks(
                        db,
                        knowledge_base,
                        document.id,
                    )
                    for chunk in chunks:
                        chunk.status = CHUNK_INDEX_FAILED_STATUS
    actor = await db.get(User, task.created_by_user_id)
    if actor is not None:
        record_audit_log(
            db,
            actor,
            f"knowledge_task.{task.task_type}.fail",
            "knowledge_task",
            task.id,
            task.task_type,
            {
                "knowledge_base_id": task.knowledge_base_id,
                "document_id": task.document_id,
                "error": message,
            },
            workspace_id=task.workspace_id,
        )
    await db.commit()


def ensure_knowledge_task_lease(lease_lost: asyncio.Event) -> None:
    if lease_lost.is_set():
        raise KnowledgePipelineError("Knowledge task lease was lost.")


async def maintain_knowledge_task_lease(
    task_id: str,
    worker_task_id: str,
    lease_lost: asyncio.Event,
) -> None:
    while True:
        await asyncio.sleep(TASK_LEASE_RENEW_SECONDS)
        try:
            async with get_session_factory()() as db:
                renewed = await knowledge_base_repository.renew_knowledge_task_lease(
                    db,
                    task_id,
                    worker_task_id,
                    utc_now() + timedelta(seconds=TASK_LEASE_SECONDS),
                )
                await db.commit()
            if not renewed:
                lease_lost.set()
                return
        except Exception:
            lease_lost.set()
            return


async def run_knowledge_task(
    task_id: str,
    settings: Settings,
    enqueue_task: Callable[[str, Settings], Awaitable[None]] | None = None,
    worker_task_id: str | None = None,
) -> str:
    chained_task_id: str | None = None
    worker_task_id = worker_task_id or new_id()
    async with get_session_factory()() as db:
        started_at = utc_now()
        claimed = await knowledge_base_repository.claim_knowledge_task(
            db,
            task_id,
            started_at,
            started_at + timedelta(seconds=TASK_LEASE_SECONDS),
            worker_task_id,
        )
        if not claimed:
            task = await db.scalar(
                select(KnowledgeTask)
                .where(KnowledgeTask.id == task_id)
                .with_for_update()
            )
            if (
                task is not None
                and task.status == "running"
                and (
                    task.lease_expires_at is None
                    or task.lease_expires_at <= started_at
                )
                and task.attempts >= task.max_attempts
            ):
                await mark_knowledge_task_failed(
                    db,
                    task_id,
                    "Knowledge task retry limit reached.",
                )
                return TASK_RUN_FINISHED
            await db.rollback()
            if task is not None and task.status == "running":
                return TASK_RUN_BUSY
            return TASK_RUN_FINISHED
        await db.commit()
        lease_lost = asyncio.Event()
        lease_heartbeat = asyncio.create_task(
            maintain_knowledge_task_lease(task_id, worker_task_id, lease_lost)
        )

        try:
            task = await knowledge_base_repository.get_knowledge_task_by_id(db, task_id)
            assert task is not None
            knowledge_base, actor, document = await get_task_scope(db, task)
            if task.task_type == TASK_PARSE:
                assert document is not None
                await run_parse_task(
                    db,
                    task,
                    knowledge_base,
                    document,
                    actor,
                    settings,
                    lease_lost,
                )
            elif task.task_type in {TASK_INDEX, TASK_REBUILD_INDEX}:
                await run_index_task(
                    db,
                    task,
                    knowledge_base,
                    document,
                    actor,
                    settings,
                    lease_lost,
                )
            else:
                raise KnowledgePipelineError("Unsupported knowledge task type.")

            ensure_knowledge_task_lease(lease_lost)
            owns_lease = await knowledge_base_repository.renew_knowledge_task_lease(
                db,
                task.id,
                worker_task_id,
                utc_now() + timedelta(seconds=TASK_LEASE_SECONDS),
            )
            if not owns_lease:
                await db.rollback()
                return TASK_RUN_FINISHED
            task.status = TASK_SUCCEEDED_STATUS
            task.lease_expires_at = None
            task.worker_task_id = None
            task.finished_at = utc_now()
            record_audit_log(
                db,
                actor,
                f"knowledge_task.{task.task_type}.succeed",
                "knowledge_task",
                task.id,
                task.task_type,
                {
                    "knowledge_base_id": task.knowledge_base_id,
                    "document_id": task.document_id,
                },
                workspace_id=task.workspace_id,
            )
            should_chain_index = (
                task.task_type == TASK_PARSE
                and document is not None
                and parse_task_options_from_task(task)["auto_index"]
            )
            await db.commit()
            if should_chain_index:
                try:
                    index_task = await enqueue_index_knowledge_document(
                        db,
                        knowledge_base,
                        document,
                        actor,
                    )
                    chained_task_id = index_task.id
                except Exception as exc:
                    await db.rollback()
                    assert document is not None
                    document.last_error = task_error_message(exc)
                    await db.commit()
        except Exception as exc:
            await db.rollback()
            await mark_knowledge_task_failed(
                db,
                task_id,
                task_error_message(exc),
                worker_task_id,
            )
            return TASK_RUN_FINISHED
        finally:
            lease_heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await lease_heartbeat

    if chained_task_id is not None:
        if enqueue_task is not None:
            await enqueue_task(chained_task_id, settings)
        else:
            await run_knowledge_task(chained_task_id, settings)
    return TASK_RUN_FINISHED


async def recover_knowledge_tasks(settings: Settings) -> None:
    async with get_session_factory()() as db:
        tasks = await knowledge_base_repository.list_recoverable_tasks(db)
        for task in tasks:
            task.status = TASK_QUEUED_STATUS
            task.started_at = None
            task.lease_expires_at = None
            task.worker_task_id = None
            task.finished_at = None
            task.processed_items = 0
        await db.commit()

    await asyncio.gather(*(run_knowledge_task(task.id, settings) for task in tasks))
