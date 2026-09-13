"""Pure unit tests for the infra feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.infra.unit
"""
import tests.support  # noqa: F401  (sets required env before app imports)

"""Pure unit tests for business services.

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.unit
"""

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException


def expect_http_error(callback, status_code: int) -> None:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == status_code, exc.status_code
        return
    raise AssertionError("expected HTTPException")

def payload_with(**fields):
    return SimpleNamespace(model_dump=lambda: fields)

def test_coverage_runner_times_out_suites() -> None:
    import importlib.util
    import subprocess
    from pathlib import Path

    path = Path(__file__).parents[2] / "scripts/coverage.py"
    spec = importlib.util.spec_from_file_location("coverage_runner", path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    original_run = runner.subprocess.run

    def timeout(*_args, **kwargs):
        assert kwargs["timeout"] == runner.COMMAND_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired("coverage", kwargs["timeout"])

    runner.subprocess.run = timeout
    log_path = None
    try:
        suite, returncode, log_path = runner._run_suite("unit", 20260818)
        assert suite == "unit"
        assert returncode == 124
        assert "timed out" in log_path.read_text()
    finally:
        runner.subprocess.run = original_run
        if log_path is not None:
            log_path.unlink(missing_ok=True)

def test_celery_worker_pool_is_fork_safe_without_prefork() -> None:
    from app.infra.queue.celery import worker_pool_for_platform

    assert worker_pool_for_platform("darwin") == "threads"
    assert worker_pool_for_platform("win32") == "solo"
    assert worker_pool_for_platform("linux") == "prefork"

def test_celery_nonfork_pool_runs_tasks_concurrently() -> None:
    import threading

    from celery.concurrency import get_implementation

    from app.infra.queue.celery import worker_pool_for_platform

    pool = get_implementation(worker_pool_for_platform("darwin"))(limit=2)
    first_started = threading.Event()
    second_started = threading.Event()
    release = threading.Event()

    def block(name: str) -> None:
        (first_started if name == "first" else second_started).set()
        if name == "first":
            release.wait(2)

    pool.start()
    try:
        pool.apply_async(block, args=("first",), callback=lambda _: None)
        assert first_started.wait(2)
        pool.apply_async(block, args=("second",), callback=lambda _: None)
        assert second_started.wait(2)
    finally:
        release.set()
        pool.stop()

def test_worker_database_rejects_in_memory_sqlite() -> None:
    from app.infra.db.session import configure_database
    from tests.support import settings

    try:
        configure_database(settings(), worker_process=True)
    except ValueError as exc:
        assert "in-memory SQLite" in str(exc)
        return
    raise AssertionError("expected in-memory SQLite worker database to be rejected")

def test_windows_event_loop_policy_is_selector_based() -> None:
    import sys

    from app.infra.runtime.event_loop import configure_windows_event_loop_policy

    original_policy = asyncio.get_event_loop_policy()
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            configure_windows_event_loop_policy()
            policy = asyncio.get_event_loop_policy()
            assert isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy)
        else:
            configure_windows_event_loop_policy()
            assert asyncio.get_event_loop_policy() is original_policy
    finally:
        asyncio.set_event_loop_policy(original_policy)


def main() -> None:
    test_coverage_runner_times_out_suites()
    test_celery_worker_pool_is_fork_safe_without_prefork()
    test_celery_nonfork_pool_runs_tasks_concurrently()
    test_worker_database_rejects_in_memory_sqlite()
    test_windows_event_loop_policy_is_selector_based()
    print("INFRA_UNIT_OK")


if __name__ == "__main__":
    main()
