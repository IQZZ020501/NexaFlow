"""Durable cleanup for temporary application uploads."""

import asyncio
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.object_storage import create_object_storage
from app.infrastructure.repositories import workflow as workflow_repository
from app.infrastructure.session import get_session_factory


async def queue_upload_cleanups(
    db: AsyncSession,
    *,
    upload_ids: list[str] | None = None,
    agent_id: str | None = None,
    workspace_id: str | None = None,
    uploaded_by_user_id: str | None = None,
) -> list[str]:
    return await workflow_repository.queue_upload_cleanups(
        db,
        upload_ids=upload_ids,
        agent_id=agent_id,
        workspace_id=workspace_id,
        uploaded_by_user_id=uploaded_by_user_id,
    )


async def run_upload_storage_cleanup(cleanup_id: str, settings: Settings) -> None:
    async with get_session_factory()() as db:
        cleanup = await workflow_repository.lock_upload_cleanup(db, cleanup_id)
        if cleanup is None:
            return
        try:
            await asyncio.to_thread(
                create_object_storage(settings.knowledge_storage_dir).delete,
                cleanup.object_key,
            )
        except Exception as exc:
            cleanup.attempts += 1
            cleanup.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            retry_seconds = min(3600, 30 * 2 ** min(cleanup.attempts - 1, 7))
            cleanup.next_attempt_at = utc_now() + timedelta(seconds=retry_seconds)
            await workflow_repository.save_upload_cleanup(db, cleanup)
            await db.commit()
            raise
        await workflow_repository.delete_upload_cleanup(db, cleanup.id)
        await db.commit()


async def prepare_due_upload_cleanups(limit: int = 100) -> list[str]:
    async with get_session_factory()() as db:
        await workflow_repository.queue_upload_cleanups(
            db,
            expired_at=utc_now(),
        )
        await db.commit()
        return await workflow_repository.list_due_upload_cleanup_ids(
            db,
            utc_now(),
            limit,
        )
