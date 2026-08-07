import os

from app.infrastructure.config import Settings
from app.infrastructure.session import configure_database

_configured_process_id: int | None = None


def configure_task_worker(settings: Settings) -> None:
    global _configured_process_id

    process_id = os.getpid()
    if _configured_process_id == process_id:
        return
    configure_database(settings, worker_process=True)
    _configured_process_id = process_id
