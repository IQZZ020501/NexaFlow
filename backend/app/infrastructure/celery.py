import sys

from celery import Celery
from celery.signals import task_failure

from app.infrastructure.config import Settings
from app.infrastructure.errors import log_error
from app.infrastructure.event_loop import configure_windows_event_loop_policy
from app.infrastructure.logger import get_logger, setup_logging

logger = get_logger("celery")


def worker_pool_for_platform(platform: str) -> str:
    # billiard's prefork pool requires os.fork() and inherited pipe handles.
    # Windows only has spawn, so prefork workers die with an invalid-handle
    # error in the pool workloop; macOS avoids unsafe HTTPS work after a
    # multithreaded fork. Both platforms run the solo pool.
    return "solo" if platform in ("darwin", "win32") else "prefork"


@task_failure.connect
def log_celery_task_failure(
    *,
    sender,
    task_id: str,
    exception: BaseException,
    **kwargs,
) -> None:
    """Global hook: every failed Celery task lands in the error log."""
    log_error(
        logger,
        "Celery task failed.",
        exception,
        task_id=task_id,
        task_name=sender.name if sender is not None else "",
    )


def create_celery_app() -> Celery:
    settings = Settings.from_env(require_bootstrap=False)
    setup_logging(level=settings.log_level)
    configure_windows_event_loop_policy()
    app = Celery(
        "app",
        broker=settings.celery_broker_url,
        include=["app.tasks.knowledge", "app.tasks.agents", "app.tasks.tools"],
    )
    app.conf.update(
        accept_content=["json"],
        task_acks_late=True,
        task_ignore_result=True,
        task_reject_on_worker_lost=True,
        task_serializer="json",
        worker_pool=worker_pool_for_platform(sys.platform),
        worker_prefetch_multiplier=1,
        beat_schedule={
            "recover-knowledge-tasks": {
                "task": "app.knowledge.recover",
                "schedule": 30.0,
            },
            "recover-knowledge-storage-cleanups": {
                "task": "app.knowledge.recover_storage_cleanups",
                "schedule": 60.0,
            },
            "recover-upload-storage-cleanups": {
                "task": "app.uploads.recover_storage_cleanups",
                "schedule": 60.0,
            },
            "recover-agent-runs": {
                "task": "app.agents.recover",
                "schedule": 30.0,
            },
            "recover-tool-invocations": {
                "task": "app.tools.recover",
                "schedule": 30.0,
            },
        },
    )
    return app


celery_app = create_celery_app()
