import os
import threading

from app.infrastructure.config import Settings
from app.infrastructure.session import configure_database

_configured_process_id: int | None = None
# ponytail: global init lock; split by settings only if worker setup becomes dynamic.
_configure_lock = threading.Lock()


def configure_task_worker(settings: Settings) -> None:
    global _configured_process_id

    process_id = os.getpid()
    if _configured_process_id == process_id:
        return
    with _configure_lock:
        if _configured_process_id == process_id:
            return
        configure_database(settings, worker_process=True)
        _configured_process_id = process_id
