"""Tests for the global logger and error-classification modules.

Run from `backend/` with `uv run python -m tests.logger`.
"""

import io
import logging
from types import SimpleNamespace
from urllib.error import URLError

from app.application.knowledge_graph_build import _log_graph_build_stage
from app.application.knowledge_graph_query import _log_graph_query_event
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


def test_graph_logs_redact_content_and_exception_body() -> None:
    setup_logging()
    handler = logging.getLogger().handlers[0]
    stream = io.StringIO()
    handler.setStream(stream)

    knowledge_base = SimpleNamespace(workspace_id="ws-1", id="kb-1")
    task = SimpleNamespace(id="task-1", task_type="graph_sync")
    revision = SimpleNamespace(
        id="rev-1",
        revision_no=2,
        model_usage_json={"model_calls": 3, "charged_tokens": 7},
    )
    _log_graph_build_stage(
        knowledge_base,
        task,
        revision,
        stage="extract",
        duration_ms=12.3,
        document_count=2,
        chunk_count=4,
        entity_count=5,
    )
    try:
        raise ValueError("SECRET_GRAPH_QUOTE_8127")
    except ValueError as exc:
        _log_graph_build_stage(
            knowledge_base,
            task,
            revision,
            stage="extract",
            duration_ms=13.4,
            document_count=2,
            chunk_count=4,
            status_value="failed",
            exc=exc,
        )
    _log_graph_query_event(
        knowledge_base,
        revision_id="rev-1",
        duration_ms=4.2,
        entity_count=3,
        claim_count=2,
        evidence_count=1,
        visited_nodes=6,
        graph_hops=4,
        truncated=True,
        limit_reason="size",
        status_value="succeeded",
    )
    try:
        raise RuntimeError("SECRET_GRAPH_QUERY_9341")
    except RuntimeError as exc:
        _log_graph_query_event(
            knowledge_base,
            revision_id="rev-1",
            duration_ms=5.2,
            status_value="failed",
            exc=exc,
        )

    output = stream.getvalue()
    assert "SECRET_GRAPH_QUOTE_8127" not in output
    assert "SECRET_GRAPH_QUERY_9341" not in output
    for marker in (
        "task_id=task-1",
        "revision_id=rev-1",
        "stage=extract",
        "stage=query",
        "entity_count=5",
        "duration_ms=12.3",
        "truncated=True",
        "limit_reason=size",
        "error_type=ValueError",
        "error_type=RuntimeError",
    ):
        assert marker in output


def main() -> None:
    test_setup_logging_idempotent()
    test_get_logger_project_prefix()
    test_classify_error()
    test_log_error_format()
    test_log_event_format()
    test_graph_logs_redact_content_and_exception_body()
    print("logger tests passed")


if __name__ == "__main__":
    main()
