"""Pure unit tests for the tools feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.tools.unit
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

def test_builtin_tool_summary_accepts_system_owner() -> None:
    from app.schemas.tools.contracts import ToolSummaryResponse

    summary = ToolSummaryResponse.model_validate(
        {
            "id": "tool-current-time",
            "workspace_id": "workspace-1",
            "kind": "builtin",
            "function_name": "current_time",
            "display_name": "Current time",
            "description": "Returns the current time.",
            "current_version_id": "version-1",
            "status": "active",
            "availability": "available",
            "source": {
                "id": "source-builtin",
                "name": "Builtins",
                "kind": "builtin",
            },
            "created_by_user_id": None,
            "created_at": "2026-08-17T00:00:00+00:00",
            "updated_at": "2026-08-18T00:00:00+00:00",
            "permission": None,
            "can_view": True,
            "can_use": True,
            "can_manage": False,
        }
    )

    assert summary.created_by_user_id is None
    assert summary.updated_at > summary.created_at

def test_tool_ref_schema_requires_canonical_ids() -> None:
    from pydantic import ValidationError

    from app.schemas.tools.contracts import ToolRefSchema

    reference = ToolRefSchema(tool_id=" tool-1 ", version_id=" version-1 ")
    assert reference.model_dump() == {
        "tool_id": "tool-1",
        "version_id": "version-1",
    }

    for payload in (
        {"tool_id": "", "version_id": "version-1"},
        {"tool_id": "tool-1", "version_id": "   "},
        {"tool_id": "tool-1", "version_id": "version-1", "server_id": "old"},
    ):
        try:
            ToolRefSchema.model_validate(payload)
        except ValidationError:
            continue
        raise AssertionError(f"Invalid HTTP ToolRef accepted: {payload}")

def test_effective_tool_access_matrix() -> None:
    from app.entities.tools import ToolAccess, effective_tool_access

    full_access = ToolAccess(can_view=True, can_use=True, can_manage=True)
    assert effective_tool_access(is_owner=True, is_workspace_admin=False, grant=None) == full_access
    assert (
        effective_tool_access(
            is_owner=False,
            is_workspace_admin=True,
            grant=None,
        )
        == full_access
    )
    assert effective_tool_access(
        is_owner=False,
        is_workspace_admin=False,
        grant="use",
    ) == ToolAccess(can_view=True, can_use=True, can_manage=False)
    assert effective_tool_access(
        is_owner=False,
        is_workspace_admin=False,
        grant="view",
    ) == ToolAccess(can_view=True, can_use=False, can_manage=False)
    assert effective_tool_access(
        is_owner=False,
        is_workspace_admin=False,
        grant=None,
    ) == ToolAccess(can_view=False, can_use=False, can_manage=False)

def test_tool_authorization_applies_builtin_and_grant_rules() -> None:
    from app.application.tools import evaluate_tool_authorization
    from app.entities.workspaces.resource_permissions import ResourcePermission
    from app.entities.tools import Tool, ToolAccess
    from app.entities.identity.user import User

    member = User(id="member-1")
    builtin = Tool(id="builtin-1", kind="builtin")
    builtin_authorization = evaluate_tool_authorization(
        builtin,
        member,
        "member",
        None,
    )
    assert builtin_authorization.access == ToolAccess(
        can_view=True,
        can_use=True,
        can_manage=False,
    )
    assert builtin_authorization.permission == "use"
    system_python = Tool(id="time-1", kind="python")
    system_python_authorization = evaluate_tool_authorization(
        system_python,
        member,
        "member",
        None,
    )
    assert system_python_authorization.access == ToolAccess(
        can_view=True,
        can_use=True,
        can_manage=False,
    )
    assert system_python_authorization.permission == "use"

    outside_workspace = evaluate_tool_authorization(
        builtin,
        member,
        None,
        None,
    )
    assert outside_workspace.access == ToolAccess(
        can_view=False,
        can_use=False,
        can_manage=False,
    )
    assert outside_workspace.permission is None

    global_admin = User(id="global-admin-1", is_global_admin=True)
    private_tool = Tool(
        id="private-1",
        kind="python",
        status="disabled",
        availability="unavailable",
        created_by_user_id="owner-1",
    )
    admin_authorization = evaluate_tool_authorization(
        private_tool,
        global_admin,
        "member",
        None,
    )
    # Workspace roles no longer widen tool access: only the owner or a grant.
    assert admin_authorization.access == ToolAccess(
        can_view=False,
        can_use=False,
        can_manage=False,
    )
    assert admin_authorization.permission is None

    former_owner = User(id="owner-1")
    former_owner_authorization = evaluate_tool_authorization(
        private_tool,
        former_owner,
        None,
        None,
    )
    assert former_owner_authorization.access == ToolAccess(False, False, False)
    assert former_owner_authorization.permission is None

    stale_grant_authorization = evaluate_tool_authorization(
        private_tool,
        member,
        None,
        ResourcePermission(permission="use", user_id=member.id),
    )
    assert stale_grant_authorization.access == ToolAccess(False, False, False)
    assert stale_grant_authorization.permission is None

    inactive_owner = User(id="owner-1", is_active=False)
    inactive_authorization = evaluate_tool_authorization(
        private_tool,
        inactive_owner,
        "member",
        None,
    )
    assert inactive_authorization.access == ToolAccess(False, False, False)
    assert inactive_authorization.permission is None

def test_python_tool_schema_validation_closes_objects() -> None:
    from app.entities.tools import validate_tool_json_schema

    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "maxLength": 200},
            "options": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
        },
        "required": ["query"],
    }

    restricted = validate_tool_json_schema(schema)

    assert restricted["additionalProperties"] is False
    assert restricted["properties"]["options"]["additionalProperties"] is False
    assert "additionalProperties" not in schema

    for invalid in (
        {"type": "string", "maxLength": 20},
        {"type": "object", "additionalProperties": True},
    ):
        try:
            validate_tool_json_schema(invalid)
        except ValueError:
            continue
        raise AssertionError(f"Unsafe Python Tool schema accepted: {invalid}")

def test_python_tool_schema_validation_enforces_limits() -> None:
    from app.entities.tools import (
        MAX_TOOL_ARRAY_ITEMS,
        MAX_TOOL_SCHEMA_BYTES,
        MAX_TOOL_SCHEMA_DEPTH,
        MAX_TOOL_SCHEMA_PROPERTIES,
        MAX_TOOL_STRING_LENGTH,
        validate_tool_json_schema,
    )

    nested: dict[str, object] = {"type": "integer"}
    for index in range(MAX_TOOL_SCHEMA_DEPTH):
        nested = {
            "type": "object",
            "properties": {f"level_{index}": nested},
        }

    invalid_schemas = (
        {
            "type": "object",
            "properties": {"remote": {"$ref": "https://example.com/schema"}},
        },
        {
            "type": "object",
            "$defs": {"value": {"type": "integer"}},
            "properties": {"local": {"$ref": "#/$defs/value"}},
        },
        {
            "type": "object",
            "description": "x" * MAX_TOOL_SCHEMA_BYTES,
        },
        {
            "type": "object",
            "properties": {
                f"field_{index}": {"type": "integer"}
                for index in range(MAX_TOOL_SCHEMA_PROPERTIES + 1)
            },
        },
        nested,
        {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"type": "integer"}}
            },
        },
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "maxItems": MAX_TOOL_ARRAY_ITEMS + 1,
                }
            },
        },
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
        },
        {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "maxLength": MAX_TOOL_STRING_LENGTH + 1,
                }
            },
        },
        {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "maxLength": 64,
                    "pattern": "^(a+)+$",
                }
            },
        },
    )
    for schema in invalid_schemas:
        try:
            validate_tool_json_schema(schema)
        except ValueError:
            continue
        raise AssertionError(f"Over-broad Python Tool schema accepted: {schema}")

def test_python_tool_schema_rejects_defs_depth_bypass() -> None:
    from app.entities.tools import (
        MAX_TOOL_SCHEMA_DEPTH,
        validate_tool_json_schema,
    )

    hidden_depth: dict[str, object] = {"type": "integer"}
    for index in range(MAX_TOOL_SCHEMA_DEPTH):
        hidden_depth = {
            "type": "object",
            "properties": {f"level_{index}": hidden_depth},
        }
    schema = {"type": "object", "$defs": {"hidden": hidden_depth}}
    try:
        validate_tool_json_schema(schema)
    except ValueError:
        return
    raise AssertionError("$defs bypassed the Tool schema depth limit.")

def test_python_tool_schema_rejects_legacy_definitions_property_bypass() -> None:
    from app.entities.tools import (
        MAX_TOOL_SCHEMA_PROPERTIES,
        validate_tool_json_schema,
    )

    schema = {
        "type": "object",
        "definitions": {
            "hidden": {
                "type": "object",
                "properties": {
                    f"field_{index}": {"type": "integer"}
                    for index in range(MAX_TOOL_SCHEMA_PROPERTIES + 1)
                },
            }
        },
    }
    try:
        validate_tool_json_schema(schema)
    except ValueError:
        return
    raise AssertionError("definitions bypassed the Tool schema property limit.")

def test_python_tool_code_is_limited_to_eight_kibibytes() -> None:
    from app.entities.tools import (
        MAX_PYTHON_TOOL_CODE_BYTES,
        validate_python_tool_code,
    )

    boundary = "x" * MAX_PYTHON_TOOL_CODE_BYTES
    assert validate_python_tool_code(boundary) == boundary

    for code in (boundary + "x", "\u754c" * (MAX_PYTHON_TOOL_CODE_BYTES // 3 + 1)):
        try:
            validate_python_tool_code(code)
        except ValueError:
            continue
        raise AssertionError("Oversized Python Tool code was accepted.")

def test_artifact_tool_accepts_sandbox_sized_content() -> None:
    from app.domain.tools.catalog.service import build_artifact_tool

    _tool, version, _policy = build_artifact_tool("workspace-1")
    assert version.input_schema["properties"]["content"]["maxLength"] == 262144

def test_documents_skill_formal_legal_contract_is_versioned() -> None:
    from app.domain.tools.catalog.service import build_skill_artifact_tool

    tool, version, _policy = build_skill_artifact_tool("workspace-1", "documents")
    rebuilt = build_skill_artifact_tool("workspace-1", "documents")[1]
    assert version.input_schema["properties"]["style"]["type"] == "string"
    assert version.input_schema["properties"]["style"]["enum"] == [
        "report",
        "formal_legal",
    ]
    assert "default" not in version.input_schema["properties"]["style"]
    assert "formal_legal" in version.description
    assert "`> `" in version.description
    assert "`---`" in version.description
    assert tool.current_version_id == version.id == rebuilt.id
    assert version.definition_hash == rebuilt.definition_hash


def test_documents_skill_reference_input_uses_bounded_large_payload_limit() -> None:
    from types import SimpleNamespace

    from app.domain.tools.runtime import (
        MAX_DOCUMENT_TOOL_INPUT_BYTES,
        MAX_TOOL_INPUT_BYTES,
        tool_input_size_limit,
        validate_tool_arguments,
    )

    snapshot = SimpleNamespace(
        function_name="documents_skill",
        input_schema={
            "type": "object",
            "properties": {"reference_docx_base64": {"type": "string"}},
        },
    )
    assert tool_input_size_limit(snapshot) == MAX_DOCUMENT_TOOL_INPUT_BYTES
    validate_tool_arguments(
        snapshot,
        {"reference_docx_base64": "x" * (MAX_TOOL_INPUT_BYTES + 1)},
    )

    ordinary_snapshot = SimpleNamespace(
        function_name="custom_tool",
        input_schema={"type": "object", "properties": {}},
    )
    assert tool_input_size_limit(ordinary_snapshot) == MAX_TOOL_INPUT_BYTES

def test_normalize_mcp_url() -> None:
    from app.ports.mcp import McpClientError, normalize_mcp_url

    assert normalize_mcp_url("  https://tools.example.com/mcp/  ") == (
        "https://tools.example.com/mcp"
    )
    assert normalize_mcp_url("http://tools.example.com/sse") == (
        "http://tools.example.com/sse"
    )
    for invalid in (
        "file:///tmp/mcp.sock",
        "https://tools.example.com/mcp?token=secret",
        "https://tools.example.com/mcp#frag",
        "https://user:pass@tools.example.com/mcp",
        "ftp://tools.example.com/mcp",
    ):
        try:
            normalize_mcp_url(invalid)
        except McpClientError:
            continue
        raise AssertionError(f"Invalid MCP URL accepted: {invalid}")


def main() -> None:
    test_builtin_tool_summary_accepts_system_owner()
    test_tool_ref_schema_requires_canonical_ids()
    test_effective_tool_access_matrix()
    test_tool_authorization_applies_builtin_and_grant_rules()
    test_python_tool_schema_validation_closes_objects()
    test_python_tool_schema_validation_enforces_limits()
    test_python_tool_schema_rejects_defs_depth_bypass()
    test_python_tool_schema_rejects_legacy_definitions_property_bypass()
    test_python_tool_code_is_limited_to_eight_kibibytes()
    test_artifact_tool_accepts_sandbox_sized_content()
    test_documents_skill_formal_legal_contract_is_versioned()
    test_normalize_mcp_url()
    print("TOOLS_UNIT_OK")


if __name__ == "__main__":
    main()
