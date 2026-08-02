from celery import Celery

from nexaflow.core.config import Settings


def create_celery_app() -> Celery:
    settings = Settings.from_env(require_bootstrap=False)
    app = Celery(
        "nexaflow",
        broker=settings.celery_broker_url,
        include=["nexaflow.tasks.knowledge"],
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
