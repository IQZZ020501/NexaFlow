"""Tests for the global logger and error-classification modules.

Run from `backend/` with `uv run python -m tests.logger`.
"""

import io
import logging
from urllib.error import URLError

from app.infrastructure.errors import (
    ExternalServiceError,
    classify_error,
    log_error,
)
from app.infrastructure.logger import get_logger, log_event, setup_logging


class _UpstreamFailure(ExternalServiceError):
    pass


class _PipelineError(Exception):
    pass


class _FakeProviderError(Exception):
    pass


_PipelineError.__module__ = "app.shareddomain.knowledge"
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


def main() -> None:
    test_setup_logging_idempotent()
    test_get_logger_project_prefix()
    test_classify_error()
    test_log_error_format()
    test_log_event_format()
    print("logger tests passed")


if __name__ == "__main__":
    main()
