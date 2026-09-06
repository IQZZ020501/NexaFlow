import asyncio
import os
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from app.infrastructure.config import Settings
from app.infrastructure.session import configure_database

_configured_process_id: int | None = None
# ponytail: global init lock; split by settings only if worker setup becomes dynamic.
_configure_lock = threading.Lock()
_event_loop: asyncio.AbstractEventLoop | None = None
_event_loop_process_id: int | None = None
_event_loop_lock = threading.Lock()
_T = TypeVar("_T")


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


def _get_task_event_loop() -> asyncio.AbstractEventLoop:
    global _event_loop, _event_loop_process_id

    process_id = os.getpid()
    if (
        _event_loop_process_id == process_id
        and _event_loop is not None
        and _event_loop.is_running()
    ):
        return _event_loop
    with _event_loop_lock:
        if (
            _event_loop_process_id == process_id
            and _event_loop is not None
            and _event_loop.is_running()
        ):
            return _event_loop
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run_event_loop() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        threading.Thread(
            target=run_event_loop,
            name="nexaflow-task-event-loop",
            daemon=True,
        ).start()
        ready.wait()
        _event_loop = loop
        _event_loop_process_id = process_id
        return loop


def run_task_async(coro: Coroutine[Any, Any, _T]) -> _T:
    settled = threading.Event()

    async def run() -> _T:
        try:
            return await coro
        finally:
            settled.set()

    future = asyncio.run_coroutine_threadsafe(run(), _get_task_event_loop())
    try:
        return future.result()
    except BaseException:
        future.cancel()
        settled.wait()
        raise
