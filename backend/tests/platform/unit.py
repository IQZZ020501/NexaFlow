"""Pure unit tests for the platform feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.platform.unit
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
from app.domain.knowledge.retrieval import (
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

def test_resource_folder_descendants_cover_nested_children() -> None:
    folders = [
        ResourceFolder(id="parent", parent_id=None),
        ResourceFolder(id="child", parent_id="parent"),
        ResourceFolder(id="grandchild", parent_id="child"),
        ResourceFolder(id="sibling", parent_id=None),
    ]
    assert descendant_folder_ids(folders, "parent") == {
        "parent",
        "child",
        "grandchild",
    }

def test_team_to_response() -> None:
    from app.entities.teams.models import Team
    from app.domain.teams.services import team_to_response

    team = Team(
        id="team-1",
        workspace_id="ws-1",
        name="Research",
        description="desc",
        status="active",
        is_default=True,
    )
    response = team_to_response(team)
    assert response.name == "Research"
    assert response.status == "active"
    assert response.is_default is True

def test_workspace_daily_quota_uses_shanghai_day_boundary() -> None:
    from datetime import UTC, datetime

    from app.application.governance.service import enforce_workspace_run_quota

    db = object()
    count_runs = AsyncMock(return_value=0)
    with (
        patch(
            "app.application.governance.service.utc_now",
            return_value=datetime(2026, 9, 5, 16, 30, tzinfo=UTC),
        ),
        patch(
            "app.application.governance.service.workspace_governance_repository.get",
            new=AsyncMock(return_value=SimpleNamespace(daily_run_limit=10)),
        ),
        patch(
            "app.application.governance.service.governance_repository.daily_run_count",
            new=count_runs,
        ),
    ):
        asyncio.run(enforce_workspace_run_quota(db, "workspace-1"))

    count_runs.assert_awaited_once_with(
        db,
        "workspace-1",
        datetime(2026, 9, 5, 16, tzinfo=UTC),
    )


def main() -> None:
    test_resource_folder_descendants_cover_nested_children()
    test_team_to_response()
    test_workspace_daily_quota_uses_shanghai_day_boundary()
    print("PLATFORM_UNIT_OK")


if __name__ == "__main__":
    main()
