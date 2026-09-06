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
from dataclasses import FrozenInstanceError
import json
from types import SimpleNamespace

import tests.support  # noqa: F401  (sets required env before app imports)

from fastapi import HTTPException
from app.application.models.registry import (
    is_masked_secret,
    normalize_model_type,
    normalize_provider_credentials,
    normalize_url_credential,
    validate_status,
)
from app.adapters.rag.retrieval import (
    MAX_PARENT_CONTEXT_CHARS,
    RankedHit,
    bounded_text_chunks,
    parent_evidence,
    parent_context,
    reciprocal_rank_fusion,
)
from app.adapters.rag.vector_store import VectorHit
from app.entities.agents import Agent
from app.entities.knowledge import KnowledgeBase
from app.entities.workspaces.resource_permissions import ResourcePermission
from app.entities.identity.user import User
from app.schemas.knowledge.graph import (
    KnowledgeGraphImportRecord,
    KnowledgeGraphReviewDecisionRequest,
)
from app.domain.agents.access.permissions import (
    effective_agent_permission,
    validate_agent_permission,
)
from app.domain.knowledge.tasks.orchestration import (
    normalized_document_artifact,
    parse_task_options,
)
from app.domain.knowledge.service import (
    clean_upload_filename,
    effective_permission,
    validate_permission,
)
from app.domain.knowledge.graph.schema import (
    GraphSchemaDefinition,
    default_graph_schema,
    graph_schema_hash,
    normalize_graph_name,
)
from app.domain.knowledge.graph.extraction import (
    EntityLexiconEntry,
    ExtractedEntity,
    ExtractionChunk,
    GraphExtractionBatch,
    build_entity_lexicon,
    deduplicate_extracted_entities,
    extract_graph_batch,
    validate_extraction_batch,
)
from app.domain.knowledge.graph.resolution import (
    claim_fingerprint,
    choose_automatic_entity_match,
    initial_claim_status,
)
from app.domain.knowledge.graph.extraction import (
    ExtractedClaim,
    _entity_type,
)
from app.domain.knowledge.graph import traversal as graph_traversal
from app.domain.knowledge.graph.traversal import (
    GraphEvidenceView,
    _collect_result_items,
    _load_path_records,
    assemble_path,
)
from app.infra.db.repositories.knowledge import graph as graph_repository
from unittest.mock import AsyncMock, patch
from app.application.knowledge.graph.build import (
    _EntityResolutionContext,
    _parse_datetime,
    _unique_surface_span,
    finalize_abandoned_graph_reservations,
)
from app.application.knowledge.graph.maintenance import _revision_source_versions
from app.application.resource_folders.service import descendant_folder_ids
from app.entities.resource_folders.models import ResourceFolder



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
    import asyncio
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
