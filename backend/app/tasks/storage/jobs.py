"""Celery entry point shared by durable storage cleanup workflows."""

from app.domain.knowledge.storage.cleanup import run_knowledge_storage_cleanup
from app.domain.workflows.uploads import run_upload_storage_cleanup
from app.infra.config.settings import Settings
from app.infra.observability.errors import log_error
from app.infra.observability.logger import get_logger
from app.infra.queue.celery import celery_app
from app.tasks.runtime import configure_task_worker, run_task_async

logger = get_logger(__name__)

STORAGE_CLEANUP_KINDS = frozenset({"knowledge", "upload"})


async def _run_storage_cleanup(
    cleanup_kind: str,
    cleanup_id: str,
    settings: Settings,
) -> None:
    if cleanup_kind == "knowledge":
        await run_knowledge_storage_cleanup(cleanup_id, settings)
        return
    if cleanup_kind == "upload":
        await run_upload_storage_cleanup(cleanup_id, settings)
        return
    raise ValueError(f"Unsupported storage cleanup kind: {cleanup_kind}")


@celery_app.task(
    bind=True,
    name="app.storage.cleanup",
    ignore_result=True,
    max_retries=None,
)
def run_storage_cleanup_job(self, cleanup_kind: str, cleanup_id: str) -> None:
    if cleanup_kind not in STORAGE_CLEANUP_KINDS:
        raise ValueError(f"Unsupported storage cleanup kind: {cleanup_kind}")
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    try:
        run_task_async(_run_storage_cleanup(cleanup_kind, cleanup_id, settings))
    except Exception as exc:
        log_error(
            logger,
            "Storage cleanup failed; retrying.",
            exc,
            cleanup_id=cleanup_id,
            cleanup_kind=cleanup_kind,
        )
        raise self.retry(exc=exc, countdown=60) from exc


__all__ = ["run_storage_cleanup_job"]
