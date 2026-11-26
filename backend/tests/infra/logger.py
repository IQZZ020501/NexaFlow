"""Tests for the global logger and error-classification modules.

Run from `backend/` with `uv run python -m tests.infra.logger`.
"""

import io
import logging
from datetime import UTC, datetime
from urllib.error import URLError

import tests.support  # noqa: F401  # sets required env before app imports

from app.infra.observability.errors import (
    ExternalServiceError,
    classify_error,
    log_error,
)
from app.infra.observability.logger import get_logger, log_event, setup_logging


class _UpstreamFailure(ExternalServiceError):
    pass


class _PipelineError(Exception):
    pass


class _FakeProviderError(Exception):
    pass


_PipelineError.__module__ = "app.domain.knowledge"
_FakeProviderError.__module__ = "openai"


def test_setup_logging_idempotent() -> None:
    setup_logging()
    setup_logging(level="DEBUG")

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG


def test_get_logger_project_prefix() -> None:
    assert get_logger().name == "NexaFlow"
    assert get_logger("app.main").name == "NexaFlow.app.main"


def test_classify_error() -> None:
    assert classify_error(None) == "internal"
    assert classify_error(ValueError("bad value")) == "internal"
    assert classify_error(URLError("timeout")) == "internal"
    assert classify_error(_PipelineError("parse failed")) == "internal"

    assert classify_error(_UpstreamFailure("LLM API down")) == "external"
    assert classify_error(_FakeProviderError("quota exceeded")) == "external"

    # An internal wrapper that hides an external cause is external.
    try:
        try:
            raise _UpstreamFailure("LLM API down")
        except _UpstreamFailure as cause:
            raise _PipelineError("pipeline failed") from cause
    except _PipelineError as exc:
        assert classify_error(exc) == "external"


def test_log_error_format() -> None:
    setup_logging()
    handler = logging.getLogger().handlers[0]
    stream = io.StringIO()
    handler.setStream(stream)

    logger = get_logger("tests")
    log_error(logger, "boom", ValueError("bad value"), agent_id="a1")
    log_error(logger, "upstream down", None, source="external", service="openai")

    output = stream.getvalue()
    assert "| NexaFlow | NexaFlow.tests | boom [source=internal] [agent_id=a1]" in output
    assert "ValueError: bad value" in output
    assert "| NexaFlow | NexaFlow.tests | upstream down [source=external] [service=openai]" in output


def test_log_event_format() -> None:
    setup_logging()
    handler = logging.getLogger().handlers[0]
    stream = io.StringIO()
    handler.setStream(stream)

    logger = get_logger("tests")
    log_event(logger, logging.INFO, "job started", task_id="t1", worker="w2")
    log_event(logger, logging.WARNING, "lease busy", task_id="t1")

    output = stream.getvalue()
    assert "| NexaFlow | NexaFlow.tests | job started [task_id=t1 worker=w2]" in output
    assert "| NexaFlow | NexaFlow.tests | lease busy [task_id=t1]" in output


def test_log_timestamps_use_shanghai() -> None:
    setup_logging()
    handler = logging.getLogger().handlers[0]
    record = logging.makeLogRecord({
        "created": datetime(2026, 11, 19, 16, 30, tzinfo=UTC).timestamp(),
        "msg": "timestamp",
    })
    handler.filter(record)
    assert handler.format(record).startswith("2026-11-20 00:30:00.000+08:00 |")


def test_server_logs_do_not_contain_request_credentials() -> None:
    setup_logging()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    access = logging.getLogger("uvicorn.access")
    error = logging.getLogger("uvicorn.error")
    access.addHandler(handler)
    error.addHandler(handler)
    marker = "synthetic" + "-credential-marker"
    try:
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1", "GET", f"/artifacts/{marker}?code={marker}", "1.1", 200)
        access.info("Unexpected access format: %s", marker)
        try:
            raise ValueError(marker)
        except ValueError:
            error.exception("Exception in ASGI application")
        error.info("Normal info without exception", exc_info=(None, None, None))
    finally:
        access.removeHandler(handler)
        error.removeHandler(handler)
    output = stream.getvalue()
    assert marker not in output
    assert "GET <route> HTTP/1.1" in output
    assert "Unhandled ValueError." in output
    assert "NoneType" not in output


def main() -> None:
    test_setup_logging_idempotent()
    test_get_logger_project_prefix()
    test_classify_error()
    test_log_error_format()
    test_log_event_format()
    test_log_timestamps_use_shanghai()
    test_server_logs_do_not_contain_request_credentials()
    print("logger tests passed")


if __name__ == "__main__":
    main()
