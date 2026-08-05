from celery import Celery

from app.infrastructure.config import Settings
from app.infrastructure.logger import setup_logging


def create_celery_app() -> Celery:
    settings = Settings.from_env(require_bootstrap=False)
    setup_logging(level=settings.log_level)
    app = Celery(
        "app",
        broker=settings.celery_broker_url,
        include=["app.tasks.knowledge"],
    )
    app.conf.update(
        accept_content=["json"],
        task_acks_late=True,
        task_ignore_result=True,
        task_reject_on_worker_lost=True,
        task_serializer="json",
        worker_prefetch_multiplier=1,
    )
    return app


celery_app = create_celery_app()
