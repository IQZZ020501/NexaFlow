from app.application.memories.extraction import extract_memories
from app.infra.config.settings import Settings
from app.infra.queue.celery import celery_app
from app.tasks.runtime import configure_task_worker, run_task_async


@celery_app.task(name="app.memories.extract", ignore_result=True)
def extract_user_memories_job(job_id: str):
    settings = Settings.from_env(require_bootstrap=False)
    configure_task_worker(settings)
    run_task_async(extract_memories(job_id, settings))
