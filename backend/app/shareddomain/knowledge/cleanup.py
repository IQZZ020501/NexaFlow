"""Durable cleanup for storage owned by deleted knowledge bases."""

import asyncio
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.knowledge import KnowledgeBase, KnowledgeStorageCleanup
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import knowledge as knowledge_repository
from app.infrastructure.session import get_session_factory
from app.ports.vector_store import delete_vector_collection
from app.shareddomain.knowledge.documents import knowledge_object_storage
from app.shareddomain.knowledge.permissions import RESOURCE_TYPE


async def purge_knowledge_base_storage(
    settings: Settings,
    workspace_id: str,
    knowledge_base_id: str,
) -> None:
    await asyncio.to_thread(delete_vector_collection, settings, knowledge_base_id)
    await asyncio.to_thread(
        knowledge_object_storage(settings).delete_prefix,
        f"{workspace_id}/{knowledge_base_id}",
    )


async def create_knowledge_storage_cleanup(
    db: AsyncSession,
    knowledge_base: KnowledgeBase,
) -> str:
    cleanup = await knowledge_repository.create_knowledge_storage_cleanup(
        db,
        KnowledgeStorageCleanup(
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_id=knowledge_base.id,
        ),
    )
    return cleanup.id


async def delete_workspace_knowledge_bases(
    db: AsyncSession,
    workspace_id: str,
) -> list[str]:
    knowledge_bases = (
        await knowledge_repository.list_and_lock_knowledge_bases_in_workspace(
            db,
            workspace_id,
        )
    )
    for knowledge_base in knowledge_bases:
        if await knowledge_repository.get_open_knowledge_base_task(
            db,
            knowledge_base,
        ) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Knowledge task is already running.",
            )

    cleanup_ids = []
    for knowledge_base in knowledge_bases:
        cleanup_ids.append(
            await create_knowledge_storage_cleanup(db, knowledge_base)
        )
        await knowledge_repository.delete_knowledge_base_graph(
            db,
            knowledge_base,
            RESOURCE_TYPE,
        )
    return cleanup_ids


async def run_knowledge_storage_cleanup(
    cleanup_id: str,
    settings: Settings,
) -> None:
    async with get_session_factory()() as db:
        cleanup = await knowledge_repository.lock_knowledge_storage_cleanup(
            db,
            cleanup_id,
        )
        if cleanup is None:
            return
        try:
            await purge_knowledge_base_storage(
                settings,
                cleanup.workspace_id,
                cleanup.knowledge_base_id,
            )
        except Exception as exc:
            cleanup.attempts += 1
            cleanup.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            retry_seconds = min(3600, 30 * 2 ** min(cleanup.attempts - 1, 7))
            cleanup.next_attempt_at = utc_now() + timedelta(seconds=retry_seconds)
            await knowledge_repository.save_knowledge_storage_cleanup(db, cleanup)
            await db.commit()
            raise
        await knowledge_repository.delete_knowledge_storage_cleanup(db, cleanup.id)
        await db.commit()


async def list_due_knowledge_storage_cleanup_ids(limit: int = 100) -> list[str]:
    async with get_session_factory()() as db:
        return await knowledge_repository.list_due_knowledge_storage_cleanup_ids(
            db,
            utc_now(),
            limit,
        )
