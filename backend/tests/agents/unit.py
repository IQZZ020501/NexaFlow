"""Pure unit tests for the agents feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.agents.unit
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

def test_effective_agent_permission_matrix() -> None:
    agent = Agent(
        id="agent-1",
        workspace_id="ws-1",
        created_by_user_id="owner-1",
    )
    owner = User(id="owner-1", username="owner")
    member = User(id="member-1", username="member")
    global_admin = User(id="super-1", username="super", is_global_admin=True)
    grant = ResourcePermission(
        workspace_id="ws-1",
        resource_type="agent",
        resource_id="agent-1",
        user_id="member-1",
        permission="view",
    )

    assert effective_agent_permission(agent, owner) == "edit"
    # roles never widen resource access, not even for system admins
    assert effective_agent_permission(agent, member) == "none"
    assert effective_agent_permission(agent, global_admin) == "none"
    assert effective_agent_permission(agent, member, grant) == "view"

def test_tool_ref_requires_stable_ids() -> None:
    from app.entities.tools import ToolRef

    reference = ToolRef(tool_id="tool-1", version_id="version-1")
    assert reference.tool_id == "tool-1"
    assert reference.version_id == "version-1"

    for fields in (
        {"tool_id": "", "version_id": "version-1"},
        {"tool_id": "tool-1", "version_id": "   "},
        {"tool_id": None, "version_id": "version-1"},
        {"tool_id": "tool-1", "version_id": 1},
    ):
        try:
            ToolRef(**fields)
        except ValueError:
            continue
        raise AssertionError(f"Invalid ToolRef accepted: {fields}")

    try:
        reference.version_id = "version-2"  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("ToolRef must be immutable.")

def test_agent_publication_snapshot_is_canonical_and_tool_versioned() -> None:
    from app.entities.agents import AgentPublicationVersion
    from app.entities.runs import AgentRun
    from app.entities.tools import ToolSnapshot
    from app.domain.agents.service import agent_publication_from_version
    from app.domain.agents.access.publications import (
        agent_publication_hash,
        build_agent_configuration_snapshot,
        build_agent_resource_snapshot,
        publication_from_snapshots,
    )

    agent = Agent(
        id="agent-1",
        workspace_id="ws-1",
        name="Research",
        description="Searches releases.",
        interaction_config={"prologue": "Hello"},
        instructions="Use tools when needed.",
        model_id="model-1",
        knowledge_query_mode="required",
    )
    first = ToolSnapshot(
        schema_version=1,
        tool_id="tool-b",
        version_id="version-b",
        source_id="source-1",
        kind="python",
        function_name="second",
        display_name="Second",
        description="",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        definition_hash="hash-b",
        policy_id="policy-b",
        policy_revision=2,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec={"code": "result = {}"},
    )
    second = ToolSnapshot(
        **{
            **first.__dict__,
            "tool_id": "tool-a",
            "version_id": "version-a",
            "function_name": "first",
            "definition_hash": "hash-a",
            "policy_id": "policy-a",
        }
    )

    configuration = build_agent_configuration_snapshot(agent)
    resources = build_agent_resource_snapshot(
        ["kb-b", "kb-a"],
        [first, second],
    )
    reordered = build_agent_resource_snapshot(
        ["kb-a", "kb-b"],
        [second, first],
    )
    assert resources == reordered
    assert [item["tool_id"] for item in resources["tools"]] == ["tool-a", "tool-b"]
    assert agent_publication_hash(configuration, resources) == agent_publication_hash(
        configuration,
        reordered,
    )

    publication = publication_from_snapshots(configuration, resources)
    assert publication.name == "Research"
    assert publication.knowledge_base_ids == ["kb-a", "kb-b"]
    assert [item.tool_id for item in publication.tools] == ["tool-a", "tool-b"]

    version = AgentPublicationVersion(
        workspace_id="ws-1",
        agent_id="agent-1",
        version_number=1,
        schema_version=1,
        configuration_snapshot=configuration,
        resource_snapshot=resources,
        configuration_hash=agent_publication_hash(configuration, resources),
        published_by_user_id="user-1",
    )
    run = AgentRun(
        workspace_id="ws-1",
        agent_id="agent-1",
        configuration_source="published",
        agent_publication_version_id=version.id,
        snapshot_schema_version=version.schema_version,
        application_snapshot={
            "configuration": configuration,
            "resources": resources,
        },
        application_snapshot_hash=version.configuration_hash,
        tool_snapshots=resources["tools"],
    )
    assert run.agent_publication_version_id == version.id
    assert run.configuration_source == "published"
    assert agent_publication_from_version(version).name == agent.name
    version.configuration_hash = "0" * 64
    try:
        agent_publication_from_version(version)
    except ValueError:
        pass
    else:
        raise AssertionError("A drifted Agent publication version was accepted.")


def test_agent_runtime_snapshots_are_versioned_and_fail_closed() -> None:
    from app.application.agents.runs.snapshots import (
        AgentRuntimePolicy,
        build_knowledge_resource_snapshot,
        build_model_runtime_snapshot,
        require_knowledge_resource_snapshot,
        require_model_runtime_snapshot,
    )
    from app.domain.models.registered import RegisteredModel
    from app.entities.defaults import utc_now

    now = utc_now()
    model = RegisteredModel(
        id="model-1",
        workspace_id="ws-1",
        name="Primary",
        provider="openai",
        provider_type="openai_compatible",
        api_base="https://models.example/v1",
        api_key_updated_at=now,
        credential_config={"api_base": "https://models.example/v1"},
        model_type="LLM",
        model_name="model-v1",
        status="active",
        meta={"request_params": {"max_tokens": 2048}},
        created_by_user_id="user-1",
        created_at=now,
        updated_at=now,
    )
    snapshot = build_model_runtime_snapshot(model)
    assert snapshot["schema_version"] == 1
    assert len(snapshot["fingerprint"]) == 64
    assert "api_key_ciphertext" not in snapshot
    require_model_runtime_snapshot(model, snapshot)

    model.model_name = "model-v2"
    try:
        require_model_runtime_snapshot(model, snapshot)
    except ValueError as exc:
        assert "changed after run creation" in str(exc)
    else:
        raise AssertionError("Model runtime drift was accepted.")
    require_model_runtime_snapshot(model, {"schema_version": 0, "legacy": True})

    knowledge_bases = [
        KnowledgeBase(
            id="kb-b",
            workspace_id="ws-1",
            name="B",
            updated_at=now,
        ),
        KnowledgeBase(
            id="kb-a",
            workspace_id="ws-1",
            name="A",
            active_graph_revision_id="revision-1",
            updated_at=now,
        ),
    ]
    content_revisions = [
        {
            "knowledge_base_id": "kb-a",
            "document_id": "document-1",
            "document_updated_at": now,
            "indexed_chunk_count": 2,
            "latest_chunk_updated_at": now,
        }
    ]
    knowledge_snapshot = build_knowledge_resource_snapshot(
        knowledge_bases,
        content_revisions,
    )
    assert [
        item["knowledge_base_id"] for item in knowledge_snapshot["resources"]
    ] == ["kb-a", "kb-b"]
    assert len(knowledge_snapshot["fingerprint"]) == 64
    require_knowledge_resource_snapshot(
        knowledge_bases,
        knowledge_snapshot,
        content_revisions,
    )
    changed_content_revisions = [
        {**content_revisions[0], "indexed_chunk_count": 3}
    ]
    try:
        require_knowledge_resource_snapshot(
            knowledge_bases,
            knowledge_snapshot,
            changed_content_revisions,
        )
    except ValueError as exc:
        assert "changed after run creation" in str(exc)
    else:
        raise AssertionError("Knowledge content drift was accepted.")
    knowledge_bases[0].status = "archived"
    try:
        require_knowledge_resource_snapshot(
            knowledge_bases,
            knowledge_snapshot,
            content_revisions,
        )
    except ValueError as exc:
        assert "changed after run creation" in str(exc)
    else:
        raise AssertionError("Knowledge resource drift was accepted.")
    require_knowledge_resource_snapshot(
        knowledge_bases,
        {"schema_version": 0, "legacy": True},
    )

    policy = AgentRuntimePolicy.from_settings(
        SimpleNamespace(
            agent_run_timeout_seconds=45,
            agent_max_turns=3,
            agent_max_tool_calls=4,
            agent_max_model_tokens=5000,
        )
    )
    assert policy == AgentRuntimePolicy(45.0, 3, 4, 5000)


def test_agent_tool_binding_requires_current_available_policy() -> None:
    from app.entities.tools import Tool, ToolPolicy, ToolSource, ToolVersion
    from app.domain.tools.access.bindings import build_bindable_tool_snapshot

    source = ToolSource(id="source-1", workspace_id="ws-1", kind="python")
    tool = Tool(
        id="tool-1",
        workspace_id="ws-1",
        source_id=source.id,
        kind="python",
        function_name="lookup",
        current_version_id="version-1",
    )
    version = ToolVersion(
        id="version-1",
        workspace_id="ws-1",
        tool_id=tool.id,
        display_name="Lookup",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        execution_spec={"code": "result = {}"},
        definition_hash="hash-1",
    )
    policy = ToolPolicy(
        id="policy-1",
        workspace_id="ws-1",
        tool_id=tool.id,
        tool_version_id=version.id,
        definition_hash=version.definition_hash,
        approval="auto",
        effect="pure",
        allowed_access_sources=["console", "public", "api"],
        workflow_callable=True,
    )
    assert (
        build_bindable_tool_snapshot(tool, source, version, policy, "user-1").tool_id
        == tool.id
    )

    tool.current_version_id = "version-2"
    expect_http_error(
        lambda: build_bindable_tool_snapshot(
            tool, source, version, policy, "user-1"
        ),
        422,
    )
    tool.current_version_id = version.id
    policy.definition_hash = "drifted"
    expect_http_error(
        lambda: build_bindable_tool_snapshot(
            tool, source, version, policy, "user-1"
        ),
        422,
    )

def test_tool_snapshot_is_an_immutable_internal_contract() -> None:
    from app.entities.tools import ToolSnapshot

    snapshot = ToolSnapshot(
        schema_version=1,
        tool_id="tool-1",
        version_id="version-1",
        source_id="source-1",
        kind="python",
        function_name="lookup_order",
        display_name="Lookup order",
        description="Returns one order.",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=3,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console", "workflow"),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec={"code": "result = inputs"},
    )

    assert snapshot.kind == "python"
    assert snapshot.execution_spec == {"code": "result = inputs"}
    try:
        snapshot.definition_hash = "hash-2"  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("ToolSnapshot must be immutable.")

def test_tool_contracts_deep_freeze_nested_json() -> None:
    import json
    from copy import copy, deepcopy
    from operator import setitem

    from app.entities.tools import ToolSnapshot, validate_tool_json_schema
    from app.application.tools.runtime.contracts import ToolRuntimeResult

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "maxLength": 64,
                "examples": ["one"],
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "maxItems": 2,
                "items": {"type": "integer"},
            }
        },
        "additionalProperties": False,
    }
    execution_spec = {
        "provider": {"name": "python", "limits": [{"cpu": 1}]}
    }
    snapshot = ToolSnapshot(
        schema_version=1,
        tool_id="tool-1",
        version_id="version-1",
        source_id="source-1",
        kind="python",
        function_name="lookup_order",
        display_name="Lookup order",
        description="Returns one order.",
        input_schema=input_schema,
        output_schema=output_schema,
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=3,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec=execution_spec,
    )
    usage = {"tokens": {"input": 1}, "providers": ["sandbox"]}
    result = ToolRuntimeResult(
        ok=True,
        data={"items": [{"id": 1}]},
        summary="Done.",
        error_code=None,
        error_message=None,
        outcome="confirmed",
        usage=usage,
    )
    assert snapshot.output_schema is not None

    mutations = (
        (snapshot.input_schema, "type", "string"),
        (snapshot.input_schema["properties"], "extra", {}),
        (snapshot.input_schema["properties"]["query"], "maxLength", 1),
        (snapshot.input_schema["properties"]["query"]["examples"], 0, "two"),
        (snapshot.input_schema["required"], 0, "other"),
        (snapshot.output_schema, "type", "array"),
        (snapshot.output_schema["properties"]["items"], "maxItems", 3),
        (snapshot.execution_spec, "provider", {}),
        (snapshot.execution_spec["provider"], "name", "mcp"),
        (snapshot.execution_spec["provider"]["limits"], 0, {}),
        (result.data, "items", []),
        (result.data["items"], 0, {}),
        (result.data["items"][0], "id", 2),
        (result.usage, "tokens", {}),
        (result.usage["tokens"], "input", 2),
        (result.usage["providers"], 0, "remote"),
    )
    for target, key, value in mutations:
        try:
            setitem(target, key, value)
        except TypeError:
            continue
        raise AssertionError(f"Nested Tool JSON remained mutable: {target}")

    input_schema["required"][0] = "changed"
    execution_spec["provider"]["limits"][0]["cpu"] = 99
    usage["tokens"]["input"] = 99
    assert isinstance(snapshot.input_schema["required"], list)
    assert snapshot.input_schema["required"] == ["query"]
    assert snapshot.execution_spec["provider"]["limits"][0]["cpu"] == 1
    assert result.usage["tokens"]["input"] == 1

    for value in (
        snapshot.input_schema,
        snapshot.output_schema,
        snapshot.execution_spec,
        result.data,
        result.usage,
    ):
        json.loads(json.dumps(value))

    for value in (
        snapshot.input_schema,
        snapshot.input_schema["required"],
    ):
        assert copy(value) is value
        assert deepcopy(value) is value
    assert validate_tool_json_schema(snapshot.input_schema) == snapshot.input_schema

def test_freeze_json_rejects_non_json_values() -> None:
    from app.entities.tools import freeze_json

    source = {
        "values": (None, False, "text", 1, 1.5),
        "nested": [{"ok": True}],
    }
    frozen = freeze_json(source)
    assert frozen == {
        "values": [None, False, "text", 1, 1.5],
        "nested": [{"ok": True}],
    }
    assert frozen is not source
    assert frozen["nested"] is not source["nested"]

    for invalid in (
        {1: "non-string key"},
        {"value": {1, 2}},
        {"value": b"bytes"},
        {"value": object()},
        float("nan"),
        float("inf"),
        float("-inf"),
    ):
        try:
            freeze_json(invalid)
        except ValueError:
            continue
        raise AssertionError(f"Non-JSON Tool value was accepted: {invalid!r}")

def test_tool_adapter_contract_is_provider_neutral() -> None:
    from datetime import datetime, timezone

    from app.entities.tools import ToolSnapshot
    from app.application.tools.runtime.contracts import (
        ToolAdapter,
        ToolInvocationContext,
        ToolRuntimeResult,
    )

    snapshot = ToolSnapshot(
        schema_version=1,
        tool_id="tool-1",
        version_id="version-1",
        source_id="source-1",
        kind="builtin",
        function_name="current_time",
        display_name="Current time",
        description="Returns the current time.",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=3,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=True,
        execution_spec={"builtin": "current_time"},
    )
    context = ToolInvocationContext(
        workspace_id="workspace-1",
        origin="agent",
        root_run_id="root-1",
        run_id="run-1",
        invocation_id="invocation-1",
        execution_user_id="user-1",
        access_source="console",
        deadline_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        idempotency_key="key-1",
    )

    class FakeAdapter:
        kind = "builtin"

        async def invoke(self, snapshot, arguments, context):
            assert snapshot.kind == self.kind
            assert arguments == {}
            assert context.workspace_id == "workspace-1"
            return ToolRuntimeResult(
                ok=True,
                data={"time": "2026-08-16T00:00:00Z"},
                summary="Current time returned.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )

    adapter = FakeAdapter()
    assert isinstance(adapter, ToolAdapter)
    result = asyncio.run(adapter.invoke(snapshot, {}, context))
    assert result.ok is True
    assert result.outcome == "confirmed"

def test_agent_tool_definition_comes_from_unified_snapshot() -> None:
    from app.application.agents.tools.builder import build_unified_agent_tool
    from app.entities.tools import ToolSnapshot

    snapshot = ToolSnapshot(
        schema_version=1,
        tool_id="tool-1",
        version_id="version-1",
        source_id="source-1",
        kind="python",
        function_name="calculate_tax",
        display_name="Calculate tax",
        description="Calculate one tax amount.",
        input_schema={
            "type": "object",
            "properties": {"amount": {"type": "number"}},
            "required": ["amount"],
            "additionalProperties": False,
        },
        output_schema=None,
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=1,
        bound_by_user_id="user-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec={"code": "result = {'tax': inputs['amount'] * 0.1}"},
    )

    tool = build_unified_agent_tool(snapshot)

    assert tool.name == "calculate_tax"
    assert tool.description == "Calculate one tax amount."
    assert tool.args_schema == snapshot.input_schema
    assert tool.metadata == {
        "display_name": "Calculate tax",
        "kind": "python",
        "server_name": "",
        "parallel_safe": False,
        "policy_mode": "",
        "server_id": "",
        "definition_hash": "hash-1",
        "source_tool_name": "",
    }

def test_agent_tool_runtime_uses_stable_invocation_identity_and_envelope() -> None:
    import hashlib

    from app.application.agents.tools.runtime import (
        agent_tool_invocation_identity,
        tool_runtime_result_to_agent_result,
    )
    from app.application.tools.runtime.contracts import ToolRuntimeResult

    invocation_id, idempotency_key = agent_tool_invocation_identity(
        "run-1",
        3,
        "call-7",
    )
    assert invocation_id == "3:call-7"
    assert idempotency_key == hashlib.sha256(
        b"agent:run-1:3:call-7"
    ).hexdigest()

    succeeded = tool_runtime_result_to_agent_result(
        ToolRuntimeResult(
            ok=True,
            data={"total": 12},
            summary="Calculated.",
            error_code=None,
            error_message=None,
            outcome="confirmed",
            usage={},
        )
    )
    assert succeeded.content == '{"total": 12}'
    assert succeeded.output == {"total": 12}
    assert succeeded.is_error is False

    uncertain = tool_runtime_result_to_agent_result(
        ToolRuntimeResult(
            ok=False,
            data=None,
            summary="Request state is unknown.",
            error_code="tool_outcome_uncertain",
            error_message="Request state is unknown.",
            outcome="uncertain",
            usage={},
        )
    )
    assert uncertain.content == "Request state is unknown."
    assert uncertain.is_error is True
    assert uncertain.outcome_uncertain is True

def test_agent_tool_call_migration_preserves_approval_gate() -> None:
    import importlib.util
    from datetime import UTC, datetime
    from pathlib import Path

    path = (
        Path(__file__).parents[2]
        / "alembic/versions/202608160005_agent_publication_versions.py"
    )
    spec = importlib.util.spec_from_file_location("agent_publication_versions", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration._migrated_tool_call_status("pending", "auto") == "queued"
    assert (
        migration._migrated_tool_call_status("pending", "each_call")
        == "awaiting_approval"
    )
    assert migration._migrated_tool_call_status("approved", "each_call") == "approved"

    assert migration._permission_backfill_action(None) == "insert"
    assert migration._permission_backfill_action("view") == "keep"
    assert migration._permission_backfill_action("use") == "keep"
    assert (
        migration._membership_history_revokes_fallback_grant(
            "workspace.member.remove", {"role": "member"}
        )
        is True
    )
    assert (
        migration._membership_history_revokes_fallback_grant(
            "workspace.member.update",
            {"previous_role": "admin", "role": "member"},
        )
        is True
    )
    assert (
        migration._membership_history_revokes_fallback_grant(
            "workspace.member.update",
            {"previous_role": "member", "role": "admin"},
        )
        is False
    )
    assert migration._agent_run_requires_drain("queued", "agent") is True
    assert migration._agent_run_requires_drain("running", "agent") is True
    assert migration._agent_run_requires_drain("succeeded", "agent") is False
    assert migration._agent_run_requires_drain("queued", "workflow") is False

    now = datetime(2026, 8, 17, tzinfo=UTC)
    assert migration._json_datetime(None) is None
    assert migration._json_datetime("not-a-date") is None
    assert migration._json_datetime(now.isoformat()) == now
    assert migration._json_datetime(now) == now

    configuration = {
        "name": "Published Agent",
        "description": "Frozen description",
        "instructions": "Frozen instructions",
        "model_id": "model-1",
        "knowledge_query_mode": "required",
        "interaction_config": {"prologue": "Hello"},
    }
    resources = {
        "knowledge_base_ids": ["kb-1"],
        "tools": [
            {
                "kind": "mcp",
                "execution_spec": {
                    "server_id": "server-1",
                    "tool_name": "lookup",
                },
            }
        ],
    }
    assert migration._legacy_publication_snapshot(configuration, resources) == {
        **configuration,
        "knowledge_base_ids": ["kb-1"],
        "mcp_tools": [{"server_id": "server-1", "tool_name": "lookup"}],
    }

    call = {
        "status": "pending",
        "approved_by_user_id": None,
        "approved_at": None,
        "result_output": None,
        "result_content": "",
        "result_summary": "",
        "result_is_error": False,
        "last_error": None,
        "started_at": None,
        "finished_at": None,
        "created_at": now,
        "updated_at": now,
    }
    expected_state = migration._migrated_invocation_state(call, now, "each_call")
    assert migration._migrated_invocation_state_matches(
        expected_state,
        {**expected_state},
    )
    assert not migration._migrated_invocation_state_matches(
        expected_state,
        {**expected_state, "status": "succeeded"},
    )

def test_unified_agent_runs_use_a_worker_generation_fence() -> None:
    from app.domain.agents.models import (
        AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS,
        AGENT_RUN_UNIFIED_QUEUED_STATUS,
        AGENT_RUN_UNIFIED_RUNNING_STATUS,
        agent_run_display_status,
        is_unified_agent_run_status,
    )

    assert AGENT_RUN_UNIFIED_QUEUED_STATUS == "queued_v2"
    assert AGENT_RUN_UNIFIED_RUNNING_STATUS == "running_v2"
    assert AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS == "awaiting_approval_v2"
    assert is_unified_agent_run_status("queued") is False
    assert is_unified_agent_run_status(AGENT_RUN_UNIFIED_QUEUED_STATUS) is True
    assert agent_run_display_status(AGENT_RUN_UNIFIED_QUEUED_STATUS) == "queued"
    assert agent_run_display_status(AGENT_RUN_UNIFIED_RUNNING_STATUS) == "running"
    assert (
        agent_run_display_status(AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS)
        == "awaiting_approval"
    )

def test_tool_invocation_identity_ignores_refreshable_deadline() -> None:
    from app.application.tools.runtime.service import _same_invocation
    from app.entities.tools import ToolInvocation
    from app.domain.tools.runtime import exhausted_tool_invocation_terminal_state

    fields = {
        "workspace_id": "workspace-1",
        "origin": "agent",
        "root_run_id": "run-1",
        "run_id": "run-1",
        "invocation_id": "2:call-1",
        "execution_user_id": "user-1",
        "access_source": "console",
        "tool_id": "tool-1",
        "tool_version_id": "version-1",
        "arguments_hash": "a" * 64,
        "idempotency_key": "agent:run-1:2:call-1",
    }
    original = ToolInvocation(
        **fields,
        policy_snapshot={
            "tool_snapshot": {"tool_id": "tool-1"},
            "deadline_at": "2026-08-17T00:00:00+00:00",
        },
    )
    resumed = ToolInvocation(
        **fields,
        policy_snapshot={
            "tool_snapshot": {"tool_id": "tool-1"},
            "deadline_at": "2026-08-17T01:00:00+00:00",
        },
    )
    changed = ToolInvocation(
        **fields,
        policy_snapshot={
            "tool_snapshot": {"tool_id": "tool-2"},
            "deadline_at": "2026-08-17T01:00:00+00:00",
        },
    )

    assert _same_invocation(original, resumed) is True
    assert _same_invocation(original, changed) is False
    assert exhausted_tool_invocation_terminal_state(
        "running",
        "external_write",
    )[:2] == ("uncertain", "uncertain")
    assert exhausted_tool_invocation_terminal_state(
        "running",
        "external_read",
    )[:2] == ("failed", "confirmed")
    assert exhausted_tool_invocation_terminal_state(
        "queued",
        "external_write",
    )[:2] == ("failed", "confirmed")

def test_public_tool_responses_exclude_execution_details() -> None:
    from app.schemas.tools.contracts import ToolDetailResponse, ToolSummaryResponse

    internal_payload = {
        "id": "tool-1",
        "workspace_id": "workspace-1",
        "kind": "mcp",
        "function_name": "lookup_order",
        "display_name": "Lookup order",
        "description": "Returns one order.",
        "current_version_id": "version-1",
        "status": "active",
        "availability": "available",
        "source": {
            "id": "source-1",
            "name": "Orders",
            "kind": "mcp",
            "transport": "streamable_http",
            "connection": {"url": "https://private.example.com/mcp"},
        },
        "created_by_user_id": "owner-1",
        "created_at": "2026-08-17T00:00:00+00:00",
        "updated_at": "2026-08-18T00:00:00+00:00",
        "permission": "use",
        "can_view": True,
        "can_use": True,
        "can_manage": False,
        "python_code": "result = inputs",
        "mcp_connection": {"bearer_token": "secret"},
        "execution_spec": {"server_id": "server-1", "tool_name": "lookup"},
    }

    summary = ToolSummaryResponse.model_validate(internal_payload).model_dump()
    detail = ToolDetailResponse.model_validate(
        {
            **internal_payload,
            "version_id": "version-1",
            "revision": 1,
            "input_schema": {"type": "object", "additionalProperties": False},
            "output_schema": {"type": "object", "additionalProperties": False},
            "approval": "each_call",
            "effect": "unknown",
            "workflow_callable": True,
            "parallel_safe": False,
        }
    ).model_dump()

    sensitive_fields = {"python_code", "mcp_connection", "execution_spec"}
    assert sensitive_fields.isdisjoint(summary)
    assert sensitive_fields.isdisjoint(detail)
    assert "connection" not in summary["source"]
    assert "connection" not in detail["source"]

def test_validate_agent_permission_only_accepts_view() -> None:
    validate_agent_permission("view")
    expect_http_error(lambda: validate_agent_permission("edit"), 422)

def test_safe_agent_error_classification() -> None:
    from app.application.agents.tools.builder import safe_agent_error
    from app.ports.llm import ModelProviderError, ModelProviderStatusError
    from app.domain.agents.runtime import AgentRunnerError

    status_error = ModelProviderStatusError(429, "rate limited")
    assert safe_agent_error(status_error) == "Provider returned status 429"

    runner_error = AgentRunnerError("planning failed")
    assert safe_agent_error(runner_error) == str(runner_error)

    provider_error = ModelProviderError("boom")
    assert safe_agent_error(provider_error) == "Agent model request failed."
    assert safe_agent_error(ValueError("other")) == "Agent execution failed."

def test_agent_process_events_update_in_place() -> None:
    from app.application.agents.runs.executor import (
        _completed_process_events,
        _upsert_process_event,
    )

    knowledge = {"type": "tool", "turn": 0, "call_id": "knowledge"}
    thought = {
        "type": "thought",
        "turn": 1,
        "tool_name": "",
        "summary": "agent.answer_ready",
    }
    tool = {"type": "tool", "turn": 1, "call_id": "mcp"}
    events = [knowledge, thought, tool]

    updated_thought = {**thought, "summary": "agent.tools_selected"}
    _upsert_process_event(events, updated_thought)

    assert events == [knowledge, updated_thought, tool]

    first_running = {
        "type": "tool",
        "turn": 2,
        "call_id": "first",
        "status": "running",
    }
    second_running = {
        "type": "tool",
        "turn": 2,
        "call_id": "second",
        "status": "running",
    }
    parallel_events: list[dict] = []
    for event in (first_running, second_running):
        _upsert_process_event(parallel_events, event)
    _upsert_process_event(parallel_events, {**second_running, "status": "succeeded"})
    _upsert_process_event(parallel_events, {**first_running, "status": "succeeded"})

    completed = _completed_process_events(parallel_events)
    assert [event["call_id"] for event in completed] == ["first", "second"]

def test_agent_event_replay_reads_every_page() -> None:
    from app.application.agents.runs import executor as agent_executor

    rows = [
        SimpleNamespace(id=index)
        for index in range(1, agent_executor.AGENT_EVENT_REPLAY_PAGE_SIZE + 3)
    ]
    calls: list[tuple[int, int]] = []

    async def list_events(_db, _run_id, after=0, limit=200):
        calls.append((after, limit))
        return [row for row in rows if row.id > after][:limit]

    original_list_events = agent_executor.agent_repository.list_agent_run_events
    agent_executor.agent_repository.list_agent_run_events = list_events
    try:
        replayed = asyncio.run(
            agent_executor._list_all_agent_run_events(
                SimpleNamespace(),
                "run-1",
            )
        )
    finally:
        agent_executor.agent_repository.list_agent_run_events = original_list_events

    assert replayed == rows
    assert calls == [
        (0, agent_executor.AGENT_EVENT_REPLAY_PAGE_SIZE),
        (
            agent_executor.AGENT_EVENT_REPLAY_PAGE_SIZE,
            agent_executor.AGENT_EVENT_REPLAY_PAGE_SIZE,
        ),
    ]

def test_stale_mcp_policy_requires_approval() -> None:
    from app.application.agents.runs import executor as agent_executor
    from app.entities.runs import AgentRun
    from app.entities.tools import McpToolPolicy
    from app.domain.agents.runtime import AgentExecutionPaused

    created_calls = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def commit(self):
            return None

    async def get_policy(*_args, **_kwargs):
        return McpToolPolicy(
            definition_hash="stale-definition",
            mode="read_only",
        )

    async def get_call(*_args, **_kwargs):
        return None

    async def create_call(_db, call):
        created_calls.append(call)
        return call

    original_factory = agent_executor.get_session_factory
    original_get_policy = agent_executor.get_mcp_tool_policy
    original_get_call = agent_executor.agent_repository.get_agent_tool_call
    original_create_call = agent_executor.agent_repository.create_agent_tool_call
    agent_executor.get_session_factory = lambda: lambda: FakeSession()
    agent_executor.get_mcp_tool_policy = get_policy
    agent_executor.agent_repository.get_agent_tool_call = get_call
    agent_executor.agent_repository.create_agent_tool_call = create_call

    async def assert_paused() -> None:
        ledger = agent_executor.DurableToolLedger(
            AgentRun(id="run-1", workspace_id="ws-1"),
            "worker-1",
            SimpleNamespace(),
            asyncio.Event(),
        )
        try:
            await ledger.before(
                1,
                {"id": "call-1", "name": "mcp_search", "arguments": "{}"},
                {
                    "kind": "mcp",
                    "server_name": "Search",
                    "server_id": "server-1",
                    "source_tool_name": "search",
                    "definition_hash": "current-definition",
                    "policy_mode": "read_only",
                },
                {},
            )
        except AgentExecutionPaused as exc:
            assert exc.call_id == "call-1"
            return
        raise AssertionError("stale read-only policy did not require approval")

    try:
        asyncio.run(assert_paused())
    finally:
        agent_executor.get_session_factory = original_factory
        agent_executor.get_mcp_tool_policy = original_get_policy
        agent_executor.agent_repository.get_agent_tool_call = original_get_call
        agent_executor.agent_repository.create_agent_tool_call = original_create_call

    assert created_calls[0].policy_mode == "approval_required"
    assert created_calls[0].approval_required is True

def test_external_mcp_policy_public_reconciles_like_console() -> None:
    from app.application.agents.runs.executor import current_mcp_policy_mode
    from app.entities.tools import McpToolPolicy

    metadata = {
        "definition_hash": "current-definition",
        "policy_mode": "read_only",
    }
    current = McpToolPolicy(
        definition_hash="current-definition",
        mode="read_only",
    )
    assert (
        current_mcp_policy_mode(
            "public",
            metadata,
            current,
            "current-definition",
        )
        == "read_only"
    )
    assert (
        current_mcp_policy_mode(
            "api",
            metadata,
            None,
            "current-definition",
        )
        == "disabled"
    )
    # Public runs reconcile like console runs: a stale or drifted policy
    # definition falls back to approval, never to a silent disable.
    assert current_mcp_policy_mode(
        "public",
        metadata,
        McpToolPolicy(
            definition_hash="stale-definition",
            mode="read_only",
        ),
        "current-definition",
    ) == "approval_required"
    assert current_mcp_policy_mode(
        "api",
        metadata,
        McpToolPolicy(
            definition_hash="current-definition",
            mode="approval_required",
        ),
        "current-definition",
    ) == "disabled"
    # A live definition that drifted from the durable call snapshot requires
    # renewed approval on public runs; only the API read-only gate compares
    # the live hash directly.
    assert current_mcp_policy_mode(
        "public",
        metadata,
        current,
        "drifted-definition",
    ) == "approval_required"
    # Disabled stays disabled everywhere, including during live drift.
    assert current_mcp_policy_mode(
        "public",
        metadata,
        McpToolPolicy(
            definition_hash="current-definition",
            mode="disabled",
        ),
        "current-definition",
    ) == "disabled"
    assert current_mcp_policy_mode(
        "public",
        metadata,
        McpToolPolicy(
            definition_hash="stale-definition",
            mode="disabled",
        ),
        "drifted-definition",
    ) == "disabled"
    # Approval-required policies now reach the approval flow on public runs.
    assert current_mcp_policy_mode(
        "public",
        metadata,
        McpToolPolicy(
            definition_hash="current-definition",
            mode="approval_required",
        ),
        "current-definition",
    ) == "approval_required"

def test_external_mcp_policy_drift_requires_public_approval_but_blocks_api() -> None:
    from app.application.agents.runs import executor as agent_executor
    from app.entities.runs import AgentRun
    from app.entities.tools import McpToolPolicy

    created_calls = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def commit(self):
            return None

    async def get_policy(*_args, **_kwargs):
        return McpToolPolicy(
            definition_hash="current-definition",
            mode="approval_required",
        )

    async def get_call(_db, run_id, _turn, _call_id):
        for call in reversed(created_calls):
            if call.run_id == run_id:
                return call
        return None

    async def resolve_tools(*_args, **_kwargs):
        return [SimpleNamespace(definition=SimpleNamespace())]

    async def create_call(_db, call):
        created_calls.append(call)
        return call

    async def block_call(_db, _call_id, reason, blocked_at, result_summary):
        call = created_calls[-1]
        call.status = "rejected"
        call.last_error = reason
        call.result_content = reason
        call.result_summary = result_summary
        call.result_is_error = True
        call.finished_at = blocked_at
        return True

    original_factory = agent_executor.get_session_factory
    original_get_policy = agent_executor.get_mcp_tool_policy
    original_get_call = agent_executor.agent_repository.get_agent_tool_call
    original_create_call = agent_executor.agent_repository.create_agent_tool_call
    original_block_call = agent_executor.agent_repository.block_agent_tool_call
    original_resolve_tools = agent_executor.resolve_mcp_tools
    original_definition_hash = agent_executor.mcp_tool_definition_hash
    agent_executor.get_session_factory = lambda: lambda: FakeSession()
    agent_executor.get_mcp_tool_policy = get_policy
    agent_executor.agent_repository.get_agent_tool_call = get_call
    agent_executor.agent_repository.create_agent_tool_call = create_call
    agent_executor.agent_repository.block_agent_tool_call = block_call
    agent_executor.resolve_mcp_tools = resolve_tools
    agent_executor.mcp_tool_definition_hash = lambda _definition: "current-definition"

    metadata = {
        "kind": "mcp",
        "server_name": "Search",
        "server_id": "server-1",
        "source_tool_name": "search",
        "definition_hash": "current-definition",
        "policy_mode": "read_only",
    }

    async def assert_public_requires_approval() -> None:
        ledger = agent_executor.DurableToolLedger(
            AgentRun(
                id="run-1",
                workspace_id="ws-1",
                access_source="public",
                consumer_id="visitor-1",
            ),
            "worker-1",
            SimpleNamespace(),
            asyncio.Event(),
        )
        try:
            await ledger.before(
                1,
                {"id": "call-1", "name": "mcp_search", "arguments": "{}"},
                metadata,
                {},
            )
        except agent_executor.AgentExecutionPaused:
            return
        raise AssertionError("expected AgentExecutionPaused")

    async def assert_api_stays_blocked() -> None:
        ledger = agent_executor.DurableToolLedger(
            AgentRun(
                id="run-2",
                workspace_id="ws-1",
                access_source="api",
                consumer_id="credential-1",
            ),
            "worker-1",
            SimpleNamespace(),
            asyncio.Event(),
        )
        result = await ledger.before(
            1,
            {"id": "call-2", "name": "mcp_search", "arguments": "{}"},
            metadata,
            {},
        )
        assert result is not None and result.is_error is True

    try:
        asyncio.run(assert_public_requires_approval())
        public_call = created_calls[-1]
        assert public_call.policy_mode == "approval_required"
        assert public_call.approval_required is True
        assert public_call.status == "awaiting_approval"
        asyncio.run(assert_api_stays_blocked())
        api_call = created_calls[-1]
        assert api_call.policy_mode == "disabled"
        assert api_call.approval_required is False
        assert api_call.status == "rejected"
    finally:
        agent_executor.get_session_factory = original_factory
        agent_executor.get_mcp_tool_policy = original_get_policy
        agent_executor.agent_repository.get_agent_tool_call = original_get_call
        agent_executor.agent_repository.create_agent_tool_call = original_create_call
        agent_executor.agent_repository.block_agent_tool_call = original_block_call
        agent_executor.resolve_mcp_tools = original_resolve_tools
        agent_executor.mcp_tool_definition_hash = original_definition_hash

def test_external_stream_epoch_is_stable_and_sanitized() -> None:
    from app.application.agents.access.service import sanitize_external_agent_stream
    from app.entities.defaults import utc_now

    now = utc_now()
    raw_epoch = "worker-task-internal-epoch"
    running = {
        "id": "run-1",
        "conversation_id": "conversation-1",
        "goal": "Question",
        "status": "running",
        "result": "",
        "created_at": now,
        "started_at": now,
        "finished_at": None,
        "updated_at": now,
    }
    completed = {
        **running,
        "status": "succeeded",
        "result": "Answer",
        "finished_at": now,
    }

    async def source():
        yield {
            "type": "run",
            "run": running,
            "sequence": 0,
            "stream_epoch": raw_epoch,
        }
        yield {
            "type": "reasoning_delta",
            "turn": 1,
            "delta": "Let me think",
            "live_sequence": "1-0",
            "stream_epoch": raw_epoch,
        }
        yield {
            "type": "tool_input_delta",
            "turn": 1,
            "call_id": "internal-call-1",
            "tool_name": "mcp_internal_search",
            "field": "query",
            "delta": "release notes",
            "replace": False,
            "live_sequence": "1-1",
            "stream_epoch": raw_epoch,
        }
        yield {
            "type": "process",
            "event": {
                "type": "thought",
                "turn": 1,
                "status": "succeeded",
                "summary": "agent.answer_ready",
                "reasoning": "Let me think",
                "call_id": "internal-call-1",
                "tool_name": "mcp_internal_search",
            },
            "sequence": 1,
            "stream_epoch": raw_epoch,
        }
        yield {
            "type": "answer_delta",
            "delta": "Answer",
            "live_sequence": "2-0",
            "stream_epoch": raw_epoch,
        }
        yield {
            "type": "complete",
            "run": completed,
            "sequence": 2,
            "stream_epoch": raw_epoch,
        }

    async def collect():
        return [event async for event in sanitize_external_agent_stream(source())]

    events = asyncio.run(collect())
    epochs = [event["stream_epoch"] for event in events]
    assert len(set(epochs)) == 1
    assert len(epochs[0]) == 32
    assert raw_epoch not in repr(events)
    assert epochs[0] != raw_epoch
    assert "internal-call-1" not in repr(events)
    reasoning_deltas = [event for event in events if event["type"] == "reasoning_delta"]
    assert len(reasoning_deltas) == 1
    assert {
        key: reasoning_deltas[0][key]
        for key in ("type", "turn", "delta")
    } == {"type": "reasoning_delta", "turn": 1, "delta": "Let me think"}
    tool_input_deltas = [
        event for event in events if event["type"] == "tool_input_delta"
    ]
    assert len(tool_input_deltas) == 1
    assert tool_input_deltas[0]["field"] == "query"
    assert tool_input_deltas[0]["delta"] == "release notes"
    assert tool_input_deltas[0]["replace"] is False
    assert tool_input_deltas[0]["tool_name"] == "mcp_internal_search"
    assert len(tool_input_deltas[0]["id"]) == 16
    progress_events = [event for event in events if event["type"] == "progress"]
    assert len(progress_events) == 1
    assert progress_events[0]["event"] == {
        "id": progress_events[0]["event"]["id"],
        "type": "answer",
        "status": "running",
        "stage": "running",
        "turn": 1,
        "count": None,
        "reasoning": "Let me think",
        "tool_name": "",
        "tool_label": "",
        "tool_kind": "unknown",
        "server_name": "",
        "input": {},
        "output": None,
        "input_truncated": False,
        "hits": [],
    }

def test_external_progress_events_carry_knowledge_hits() -> None:
    from app.application.agents.access.service import external_progress_events

    events = [
        {
            "type": "tool",
            "turn": 0,
            "tool_name": "search_knowledge",
            "tool_kind": "knowledge",
            "status": "running",
            "summary": "agent.tool_running",
            "call_id": "call-1",
        },
        {
            "type": "tool",
            "turn": 0,
            "tool_name": "search_knowledge",
            "tool_kind": "knowledge",
            "status": "succeeded",
            "summary": "agent.knowledge_chunks_returned:2",
            "call_id": "call-1",
            "output": {
                "query": "release process",
                "hits": [
                    {
                        "knowledge_base": "Release KB",
                        "document": "release.md",
                        "content": "Cut the release on Fridays.",
                    },
                    {
                        "knowledge_base": "Release KB",
                        "document": "handbook.md",
                        "content": "Tag with semantic versions.",
                    },
                    "not-a-dict",
                ],
                "evidence_status": "found",
            },
        },
    ]
    progress = external_progress_events(events, "succeeded")
    assert len(progress) == 1
    event = progress[0]
    assert event.type == "knowledge"
    assert event.status == "succeeded"
    assert event.count == 2
    assert [hit.model_dump() for hit in event.hits] == [
        {
            "knowledge_base": "Release KB",
            "document": "release.md",
            "content": "Cut the release on Fridays.",
        },
        {
            "knowledge_base": "Release KB",
            "document": "handbook.md",
            "content": "Tag with semantic versions.",
        },
    ]

def test_external_progress_events_carry_mcp_tool_details() -> None:
    from app.application.agents.access.service import external_progress_events

    progress = external_progress_events(
        [
            {
                "type": "tool",
                "turn": 1,
                "tool_name": "web_search",
                "tool_label": "Web search",
                "tool_kind": "mcp",
                "server_name": "Tavily",
                "status": "succeeded",
                "summary": "agent.tool_running",
                "call_id": "call-2",
                "input": {"query": "GitHub trending"},
                "output": {"results": [{"title": "NexaFlow"}]},
            }
        ],
        "succeeded",
    )

    assert len(progress) == 1
    event = progress[0]
    assert event.tool_name == "web_search"
    assert event.tool_label == "Web search"
    assert event.tool_kind == "mcp"
    assert event.server_name == "Tavily"
    assert event.input == {"query": "GitHub trending"}
    assert event.output == {"results": [{"title": "NexaFlow"}]}

def test_external_progress_events_bound_tool_inputs_and_pass_output() -> None:
    import json

    from app.application.agents.access.service import (
        TOOL_INPUT_LIMITS,
        _bounded_tool_payload,
        external_progress_events,
    )

    # input 用紧限制：字符串/深度/集合/全局预算都被约束
    oversized = {
        "query": "x" * (TOOL_INPUT_LIMITS.max_string + 100),
        "nested": {"deep": {"deeper": {"deepest": {"value": "too deep"}}}},
        "items": list(range(100)),
    }
    bounded, truncated = _bounded_tool_payload(oversized, TOOL_INPUT_LIMITS)
    assert truncated
    assert len(bounded["query"]) <= TOOL_INPUT_LIMITS.max_string + 1
    assert len(bounded["items"]) <= TOOL_INPUT_LIMITS.max_items
    assert bounded["nested"]["deep"]["deeper"]["deepest"] == "…"
    assert len(json.dumps(bounded)) < TOOL_INPUT_LIMITS.max_serialized

    # input 全局预算：结构巨大时整体受限，序列化保持有界
    huge = {"key": {f"k{i}": "v" * 200 for i in range(100)}}
    bounded_huge, huge_truncated = _bounded_tool_payload(huge, TOOL_INPUT_LIMITS)
    assert huge_truncated
    assert len(json.dumps(bounded_huge)) < TOOL_INPUT_LIMITS.max_serialized

    # input 扁平超大 dict：只消费前 max_items 项，不 materialize 全部
    flat = {f"key-{i}": "value" for i in range(10000)}
    bounded_flat, flat_truncated = _bounded_tool_payload(flat, TOOL_INPUT_LIMITS)
    assert flat_truncated
    assert len(bounded_flat) <= TOOL_INPUT_LIMITS.max_items

    # output 完整透传：事件中的任意大小/深度结果原样返回，不截断
    huge_output = {
        "text": "z" * 50000,
        "nested": {"a": {"b": {"c": {"d": {"e": {"f": {"g": "deep"}}}}}}},
        "rows": list(range(5000)),
    }
    progress = external_progress_events(
        [
            {
                "type": "tool",
                "turn": 1,
                "tool_kind": "mcp",
                "status": "succeeded",
                "summary": "agent.tool_running",
                "call_id": "call-3",
                "input": {"query": "x" * (TOOL_INPUT_LIMITS.max_string + 50)},
                "output": huge_output,
            }
        ],
        "succeeded",
    )
    assert progress[0].input_truncated is False
    assert progress[0].input == {
        "query": "x" * (TOOL_INPUT_LIMITS.max_string + 50)
    }
    assert progress[0].output == huge_output

def test_external_progress_events_knowledge_failure_has_no_hits() -> None:
    from app.application.agents.access.service import external_progress_events

    progress = external_progress_events(
        [
            {
                "type": "tool",
                "turn": 0,
                "tool_name": "search_knowledge",
                "tool_kind": "knowledge",
                "status": "failed",
                "summary": "Knowledge search unavailable.",
                "call_id": "call-1",
                "output": {"query": "missing", "hits": [], "evidence_status": "unavailable"},
            }
        ],
        "failed",
    )
    assert len(progress) == 1
    event = progress[0]
    assert event.status == "failed"
    assert event.hits == []

def test_external_progress_events_include_grounding_stage() -> None:
    from app.application.agents.access.service import external_progress_events

    progress = external_progress_events(
        [
            {
                "type": "thought",
                "turn": 1,
                "status": "succeeded",
                "summary": "agent.grounding_inline",
                "call_id": "grounding-1",
            },
        ],
        "succeeded",
    )
    assert len(progress) == 1
    assert progress[0].type == "analysis"
    assert progress[0].status == "succeeded"
    assert progress[0].stage == "completed"

    skipped = external_progress_events(
        [
            {
                "type": "thought",
                "turn": 1,
                "status": "succeeded",
                "summary": "agent.grounding_skipped",
                "call_id": "grounding-2",
            }
        ],
        "succeeded",
    )
    assert len(skipped) == 1
    assert skipped[0].status == "succeeded"
    assert skipped[0].stage == "completed"

def test_mcp_policy_concurrent_first_write_reloads_existing() -> None:
    from sqlalchemy.exc import IntegrityError

    from app.entities.tools import McpToolPolicy
    from app.entities.defaults import utc_now
    from app.infra.db.repositories.tools import mcp as mcp_repository
    from app.domain.tools.models import McpToolPolicy as McpToolPolicyOrm

    now = utc_now()
    existing = McpToolPolicyOrm(
        id="policy-existing",
        workspace_id="ws-1",
        mcp_server_id="server-1",
        tool_name="search",
        definition_hash="old-definition",
        mode="approval_required",
        reviewed_by_user_id="user-old",
        reviewed_at=now,
        created_at=now,
        updated_at=now,
    )

    class FakeSavepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeSession:
        def __init__(self) -> None:
            self.scalar_calls = 0
            self.flush_calls = 0

        async def scalar(self, _statement):
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else existing

        def begin_nested(self):
            return FakeSavepoint()

        def add(self, _row):
            return None

        async def flush(self):
            self.flush_calls += 1
            if self.flush_calls == 1:
                raise IntegrityError("insert", {}, Exception("unique"))

    async def save_policy() -> McpToolPolicy:
        return await mcp_repository.save_mcp_tool_policy(
            FakeSession(),  # type: ignore[arg-type]
            McpToolPolicy(
                workspace_id="ws-1",
                mcp_server_id="server-1",
                tool_name="search",
                definition_hash="current-definition",
                mode="read_only",
                reviewed_by_user_id="user-new",
                reviewed_at=now,
            ),
        )

    saved = asyncio.run(save_policy())
    assert saved.id == "policy-existing"
    assert saved.definition_hash == "current-definition"
    assert saved.mode == "read_only"
    assert saved.reviewed_by_user_id == "user-new"
    assert saved.created_at == now

def test_mcp_function_name_is_stable_and_sanitized() -> None:
    import hashlib

    from mcp.types import Tool as McpTool

    from app.application.agents.tools.builder import build_mcp_agent_tool, mcp_function_name
    from app.entities.tools import McpServer
    from app.domain.tools.mcp.service import ResolvedMcpTool

    server = McpServer(id="server-1", name="orders")
    tool = ResolvedMcpTool(
        server=server,
        definition=McpTool(
            name="order items!",
            input_schema={"type": "object"},
            description="",
            annotations={"readOnlyHint": True, "destructiveHint": False},
        ),
    )
    name = mcp_function_name(tool)
    assert name.startswith("mcp_order_items_")
    digest = hashlib.sha256(b"server-1:order items!").hexdigest()[:8]
    assert name == f"mcp_order_items_{digest}"
    # deterministic for the same server/tool pair
    assert mcp_function_name(tool) == name
    built = build_mcp_agent_tool(tool, SimpleNamespace(), "agent-1")
    assert built.metadata is not None
    assert built.metadata["policy_mode"] == "approval_required"

def test_run_to_response_maps_run_fields() -> None:
    from app.application.agents.tools.builder import knowledge_source_ref, run_to_response
    from app.entities.runs import AgentRun

    run = AgentRun(
        id="run-1",
        workspace_id="ws-1",
        agent_id="agent-1",
        requested_by_user_id="user-1",
        conversation_id="conversation-1",
        goal="goal",
        instructions="instructions",
        model_id="model-1",
        model_name="deepseek-chat",
        status="succeeded",
        result="answer",
        model_usage={"model_calls": 1, "total_tokens": 12},
        grounding_meta={"evidence_ids": ["chunk-2"]},
        events=[
            {
                "type": "tool",
                "turn": 1,
                "tool_name": "search_knowledge",
                "tool_kind": "knowledge",
                "status": "succeeded",
                "summary": "agent.knowledge_chunks_returned:2",
                "output": {
                    "hits": [
                        {
                            "knowledge_base": "制度库",
                            "document": "社保制度.pdf",
                            "chunk_id": "chunk-1",
                            "chunk_index": 0,
                            "content": "不相关片段",
                        },
                        {
                            "knowledge_base": "制度库",
                            "document": "社保制度.pdf",
                            "chunk_id": "chunk-2",
                            "parent_title": "补缴规则",
                            "section_path": ["第二章", "补缴规则"],
                            "chunk_index": 4,
                            "content": "不足十五年时可以补缴。",
                        },
                    ]
                },
            }
        ],
        application_snapshot={
            "attachments": [
                {
                    "filename": "report.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 12,
                    "category": "document",
                }
            ]
        },
    )
    response = run_to_response(run, trace_id="trace-1")
    child = AgentRun(id="child-1", parent_run_id="parent-1", root_run_id="")
    assert child.root_run_id == "parent-1"
    assert response.id == "run-1"
    assert response.workspace_id == "ws-1"
    assert response.agent_id == "agent-1"
    assert response.conversation_id == "conversation-1"
    assert response.status == "succeeded"
    assert response.result == "answer"
    assert response.model_name == "deepseek-chat"
    assert response.plan == []
    assert len(response.events) == 1
    assert response.model_usage["total_tokens"] == 12
    assert response.attachments[0].filename == "report.pdf"
    assert response.sources[0].document == "社保制度.pdf"
    assert response.sources[0].source_ref == knowledge_source_ref("chunk-2")
    assert response.sources[0].parent_title == "补缴规则"
    assert response.sources[0].chunk_index == 4
    assert response.sources[0].content == "不足十五年时可以补缴。"
    assert response.trace_id == "trace-1"


def test_run_response_normalizes_legacy_source_links() -> None:
    from app.application.agents.tools.builder import (
        knowledge_source_ref,
        normalize_agent_source_links,
        run_to_response,
    )
    from app.entities.runs import AgentRun

    chunk_id = "550e8400-e29b-41d4-a716-446655440000"
    source_ref = knowledge_source_ref(chunk_id)
    events = [
        {
            "type": "tool",
            "turn": 1,
            "tool_name": "search_knowledge",
            "tool_kind": "knowledge",
            "status": "succeeded",
            "summary": "agent.knowledge_chunks_returned:1",
            "call_id": "call-1",
            "tool_label": "knowledge",
            "server_name": "",
            "input": {},
            "duration_ms": 0,
            "output": {
                "hits": [
                    {
                        "chunk_id": chunk_id,
                        "source_ref": source_ref,
                        "contributing_chunk_ids": [chunk_id],
                    }
                ]
            },
        }
    ]
    content = (
        f"第一处 [source] (#nexfaow-source-{chunk_id})。"
        f"第二处 [source](#nexaflow-source-{source_ref.upper()})。"
        f"第三处 [source](https://example.test/#nexaflow-source-{chunk_id})。"
    )
    normalized = normalize_agent_source_links(content, events)
    expected = f"[source](#nexaflow-source-{source_ref})"
    assert normalized == f"第一处 {expected}。第二处 {expected}。第三处 {expected}。"

    run = AgentRun(
        id="run-legacy-citation",
        workspace_id="ws-1",
        agent_id="agent-1",
        goal="goal",
        model_id="model-1",
        model_name="model",
        status="succeeded",
        result=content,
        events=events,
    )
    assert run_to_response(run).result == normalized

def test_regenerated_agent_run_starts_from_a_fresh_checkpoint() -> None:
    from app.application.agents.runs.service import build_regenerated_agent_run
    from app.entities.runs import AgentRun

    source = AgentRun(
        id="run-source",
        workspace_id="ws-1",
        agent_id="agent-1",
        requested_by_user_id="user-1",
        execution_user_id="user-1",
        access_source="console",
        consumer_id="user-1",
        conversation_id="conversation-1",
        goal="Explain the release notes",
        attachment_context="attached context",
        instructions="Answer precisely.",
        knowledge_base_ids=["kb-1"],
        configuration_source="draft",
        model_id="model-1",
        model_name="deepseek-chat",
        status="succeeded",
        checkpoint={"final_answer": "old answer"},
        checkpoint_phase="done",
        result="old answer",
        events=[{"type": "answer"}],
        feedback="positive",
    )

    regenerated = build_regenerated_agent_run(
        source,
        User(id="user-1", username="owner"),
        "Edited release notes",
    )

    assert regenerated.id != source.id
    assert regenerated.regenerated_from_run_id == source.id
    assert regenerated.conversation_id == source.conversation_id
    assert regenerated.goal == "Edited release notes"
    assert regenerated.attachment_context == source.attachment_context
    assert regenerated.status == "queued_v2"
    assert regenerated.checkpoint == {}
    assert regenerated.checkpoint_phase == "agent"
    assert regenerated.result == ""
    assert regenerated.events == []
    assert regenerated.feedback is None

def test_edit_regeneration_rejects_a_non_latest_run() -> None:
    from app.application.agents.runs.service import regenerate_agent_run_from_source
    from app.entities.runs import AgentRun

    source = AgentRun(
        id="run-source",
        agent_id="agent-1",
        access_source="console",
        consumer_id="user-1",
        conversation_id="conversation-1",
        status="succeeded",
    )
    with (
        patch(
            "app.application.agents.runs.service.validate_regeneration_source",
            new=AsyncMock(),
        ),
        patch(
            "app.application.agents.runs.service.agent_repository.list_agent_runs",
            new=AsyncMock(return_value=[AgentRun(id="run-latest")]),
        ),
    ):
        try:
            asyncio.run(
                regenerate_agent_run_from_source(
                    SimpleNamespace(),
                    source,
                    User(id="user-1", username="owner"),
                    SimpleNamespace(),
                    goal="Edited question",
                )
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("expected HTTPException")

def test_repeated_run_feedback_write_is_idempotent() -> None:
    from unittest.mock import AsyncMock, patch

    from app.application.runs.feedback import update_run_feedback
    from app.entities.runs import AgentRun
    from app.entities.defaults import utc_now

    feedback_updated_at = utc_now()
    run = AgentRun(
        id="run-1",
        status="succeeded",
        result="answer",
        feedback="positive",
        feedback_updated_at=feedback_updated_at,
    )

    class FakeDatabase:
        def __init__(self) -> None:
            self.commits = 0

        async def commit(self) -> None:
            self.commits += 1

    db = FakeDatabase()
    save_run = AsyncMock(side_effect=lambda _db, current: current)
    with patch(
        "app.application.agents.runs.service.agent_repository.save_agent_run",
        new=save_run,
    ):
        updated = asyncio.run(
            update_run_feedback(db, run, "positive")  # type: ignore[arg-type]
        )

    assert updated is run
    assert run.feedback_updated_at == feedback_updated_at
    save_run.assert_not_awaited()
    assert db.commits == 0

def test_agent_usage_normalizes_provider_metadata() -> None:
    from langchain_core.messages import AIMessage

    from app.domain.agents.runtime import (
        add_compaction_usage,
        merge_usage,
        usage_from_message,
    )

    standard = usage_from_message(
        AIMessage(
            content="one",
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 3,
                "total_tokens": 13,
                "input_token_details": {"cache_read": 4},
            },
        )
    )
    openai_compatible = usage_from_message(
        AIMessage(
            content="two",
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 2,
                    "total_tokens": 9,
                }
            },
        )
    )
    unreported = usage_from_message(AIMessage(content="three"))
    merged = merge_usage(standard, openai_compatible, unreported)

    assert merged["model_calls"] == 3
    assert merged["reported_model_calls"] == 2
    assert merged["input_tokens"] == 17
    assert merged["output_tokens"] == 5
    assert merged["total_tokens"] == 22
    assert merged["cache_read_input_tokens"] == 4

    compacted = add_compaction_usage(None, standard)
    assert compacted["model_calls"] == 1
    assert compacted["compaction"]["total_tokens"] == 13


def test_knowledge_context_is_compact_for_repeated_model_turns() -> None:
    from app.application.agents.tools.builder import (
        MAX_KNOWLEDGE_CONTEXT_CHARS,
        MAX_KNOWLEDGE_CONTEXT_CONTENT_CHARS,
        bounded_knowledge_context,
    )

    payload = {
        "query": "company wage dispute",
        "evidence_status": "found",
        "retrieval_stats": [{"knowledge_base_name": "Labor law"}],
        "hits": [
            {
                "knowledge_base": "Labor law",
                "document": "labor-law.md",
                "source_ref": "source-ref",
                "chunk_id": "chunk-1",
                "document_id": "document-1",
                "content": "evidence " * 2_000,
                "distance": 0.2,
                "similarity": 0.9,
                "trace_id": "trace-id",
                "graph_claim_ids": [f"claim-{index}" for index in range(400)],
                "sources": ["keywords", "vector"],
            }
        ],
    }

    context = bounded_knowledge_context(payload)
    assert len(context) <= MAX_KNOWLEDGE_CONTEXT_CHARS
    compact = json.loads(context)
    hit = compact["hits"][0]
    assert len(hit["content"]) <= MAX_KNOWLEDGE_CONTEXT_CONTENT_CHARS
    assert hit["content_truncated"] is True
    assert "distance" not in hit
    assert "similarity" not in hit
    assert "trace_id" not in hit
    assert len(hit["graph_claim_ids"]) <= 20
    assert compact["context_truncated"] is True


def test_agent_memory_compacts_old_turns() -> None:
    from langchain_core.messages import AIMessage

    from app.application.agents.runs import memory as agent_memory
    from app.entities.runs import AgentRun

    history = [
        AgentRun(
            id=f"run-{index}",
            workspace_id="ws-1",
            agent_id="agent-1",
            requested_by_user_id="user-1",
            conversation_id="conversation-1",
            goal=f"question-{index}",
            result="x" * 3000,
            status="succeeded",
        )
        for index in range(8)
    ]
    current = AgentRun(
        id="run-current",
        workspace_id="ws-1",
        agent_id="agent-1",
        requested_by_user_id="user-1",
        conversation_id="conversation-1",
        goal="current question",
        status="running",
    )
    saved: list[tuple[str, str]] = []
    requested_limits: list[int] = []

    class FakeDatabase:
        async def flush(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    class FakeModel:
        profile = {"max_input_tokens": 4096}

        async def ainvoke(self, _messages):
            return AIMessage(
                content="Stable summary",
                usage_metadata={
                    "input_tokens": 20,
                    "output_tokens": 4,
                    "total_tokens": 24,
                },
            )

    async def list_runs(_db, _run, *, limit):
        requested_limits.append(limit)
        return None, history

    async def save_summary(_db, run, summary):
        saved.append((run.id, summary))
        return True

    original_list = agent_memory.agent_repository.list_conversation_memory_runs
    original_save = agent_memory.agent_repository.save_conversation_summary
    agent_memory.agent_repository.list_conversation_memory_runs = list_runs
    agent_memory.agent_repository.save_conversation_summary = save_summary
    try:
        prepared = asyncio.run(
            agent_memory.prepare_conversation_memory(
                FakeDatabase(),  # type: ignore[arg-type]
                current,
                SimpleNamespace(meta={}),
                FakeModel(),
                [
                    {"role": "system", "content": "rules"},
                    {"role": "user", "content": "current question"},
                ],
                [],
            )
        )
    finally:
        agent_memory.agent_repository.list_conversation_memory_runs = original_list
        agent_memory.agent_repository.save_conversation_summary = original_save

    assert saved == [("run-0", "Stable summary")]
    assert requested_limits == [agent_memory.MAX_MEMORY_RUNS]
    assert prepared.messages[0]["content"].endswith("Stable summary")
    assert prepared.model_usage["compaction"]["total_tokens"] == 24

    tight = agent_memory._fit_memory("s" * 1000, history[-1:], 128)
    assert [message["role"] for message in tight] == ["user", "assistant"]
    assert agent_memory._approx_tokens(tight) <= 128
    assert agent_memory._memory_budget(
        [{"role": "user", "content": "x" * 5000}],
        [],
        SimpleNamespace(meta={}),
        FakeModel(),
    ) == 0

def test_agent_memory_query_is_bounded_and_projected() -> None:
    from app.entities.runs import AgentRun
    from app.infra.db.repositories.agents import repository as agent_repository
    from sqlalchemy.dialects import postgresql

    statements = []

    class EmptyResult:
        def mappings(self):
            return self

        def first(self):
            return None

        def all(self):
            return []

    class FakeDatabase:
        async def execute(self, statement):
            statements.append(statement)
            return EmptyResult()

    asyncio.run(
        agent_repository.list_conversation_memory_runs(
            FakeDatabase(),  # type: ignore[arg-type]
            AgentRun(
                workspace_id="ws-1",
                agent_id="agent-1",
                requested_by_user_id="user-1",
                conversation_id="conversation-1",
            ),
            limit=7,
        )
    )
    compiled = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for statement in statements
    ]
    assert "LIMIT 7" in compiled[-1]
    for sql in compiled:
        assert "agent_runs.goal" in sql
        assert "agent_run_states.result" in sql
        assert "agent_run_states.context_summary" in sql
        assert "agent_run_snapshots" not in sql
        assert "agent_run_events" not in sql
        assert "agent_run_states.plan" not in sql
        assert "agent_run_states.checkpoint" not in sql

def test_mcp_server_to_response() -> None:
    from app.entities.tools import (
        McpServer,
        McpToolPolicy,
        Tool,
        ToolPolicy,
        ToolSource,
        ToolVersion,
    )
    from app.domain.tools.catalog.service import McpCatalogLeaf
    from app.domain.tools.mcp.service import (
        effective_mcp_tool_policy_mode,
        mcp_server_to_response,
        mcp_tool_definition_hash,
    )
    from mcp.types import Tool as McpTool

    server = McpServer(
        id="mcp-1",
        workspace_id="ws-1",
        name="docs",
        url="https://tools.example.com/mcp",
        bearer_token_ciphertext="cipher",
        bearer_token_hint="abcd",
        tools=[
            {
                "name": "search",
                "description": "Search public records.",
                "input_schema": {"type": "object"},
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                },
            },
            {
                "name": "unknown",
                "description": "Unclassified operation.",
                "input_schema": {"type": "object"},
            },
        ],
        status="active",
        last_error=None,
        created_by_user_id="user-1",
    )
    source = ToolSource(
        id="source-1",
        workspace_id="ws-1",
        mcp_server_id="mcp-1",
        kind="mcp",
        created_by_user_id="user-1",
    )
    search_tool = Tool(
        id="tool-search",
        workspace_id="ws-1",
        source_id=source.id,
        kind="mcp",
        stable_key="search",
        function_name="mcp_search_12345678",
        current_version_id="version-search",
        created_by_user_id="user-1",
    )
    search_definition = McpTool(
        name="search",
        description="Search public records.",
        input_schema={"type": "object"},
        annotations={"readOnlyHint": True, "destructiveHint": False},
    )
    search_hash = mcp_tool_definition_hash(search_definition)
    search_version = ToolVersion(
        id="version-search",
        workspace_id="ws-1",
        tool_id=search_tool.id,
        description="Search public records.",
        input_schema={"type": "object"},
        execution_spec={
            "server_id": "mcp-1",
            "tool_name": "search",
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
        },
        definition_hash=search_hash,
    )
    stale_policy = ToolPolicy(
        workspace_id="ws-1",
        tool_id=search_tool.id,
        tool_version_id=search_version.id,
        definition_hash="stale",
        approval="auto",
        effect="external_read",
    )
    unknown_tool = Tool(
        id="tool-unknown",
        workspace_id="ws-1",
        source_id=source.id,
        kind="mcp",
        stable_key="unknown",
        function_name="mcp_unknown_12345678",
        current_version_id="version-unknown",
        created_by_user_id="user-1",
    )
    unknown_version = ToolVersion(
        id="version-unknown",
        workspace_id="ws-1",
        tool_id=unknown_tool.id,
        description="Unclassified operation.",
        input_schema={"type": "object"},
        execution_spec={
            "server_id": "mcp-1",
            "tool_name": "unknown",
            "annotations": None,
        },
        definition_hash="u" * 64,
    )
    leaves = [
        McpCatalogLeaf(source, search_tool, search_version, stale_policy),
        McpCatalogLeaf(source, unknown_tool, unknown_version, None),
    ]
    response = mcp_server_to_response(server, leaves)
    assert response.id == "mcp-1"
    assert response.workspace_id == "ws-1"
    assert response.url == "https://tools.example.com/mcp"
    assert response.has_bearer_token is True
    assert response.bearer_token_hint == "abcd"
    assert response.tools[0].policy_mode == "approval_required"
    assert response.tools[1].policy_mode == "approval_required"

    assert mcp_server_to_response(server).tools == []
    assert (
        effective_mcp_tool_policy_mode(
            McpTool(
                name="delete",
                input_schema={"type": "object"},
                annotations={"readOnlyHint": True, "destructiveHint": True},
            ),
            None,
        )
        == "approval_required"
    )
    stale_policy.definition_hash = search_hash
    response = mcp_server_to_response(server, leaves)
    assert response.tools[0].policy_mode == "read_only"
    assert response.tools[0].definition_hash == search_hash

def test_unified_mcp_policy_projection_fails_closed_and_honors_kill_switch() -> None:
    from app.entities.tools import Tool, ToolPolicy, ToolSource, ToolVersion
    from app.domain.tools.catalog.service import (
        McpCatalogLeaf,
        legacy_mcp_policy_mode,
    )

    source = ToolSource(id="source-1", workspace_id="ws-1", kind="mcp")
    tool = Tool(
        id="tool-1",
        workspace_id="ws-1",
        source_id=source.id,
        kind="mcp",
        current_version_id="version-2",
    )
    version = ToolVersion(
        id="version-2",
        workspace_id="ws-1",
        tool_id=tool.id,
        definition_hash="b" * 64,
    )
    policy = ToolPolicy(
        workspace_id="ws-1",
        tool_id=tool.id,
        tool_version_id=version.id,
        definition_hash=version.definition_hash,
        approval="auto",
        effect="external_read",
    )
    leaf = McpCatalogLeaf(source=source, tool=tool, version=version, policy=policy)
    assert legacy_mcp_policy_mode(leaf) == "read_only"

    policy.definition_hash = "a" * 64
    assert legacy_mcp_policy_mode(leaf) == "approval_required"

    tool.status = "disabled"
    assert legacy_mcp_policy_mode(leaf) == "disabled"

def test_agent_live_stream_round_trip() -> None:
    from app.infra.agents import live_stream as agent_live_stream
    from tests.support import settings

    class FakeRedis:
        def __init__(self) -> None:
            self.entries: list[tuple[str, dict[str, str]]] = []
            self.expirations: list[tuple[str, int]] = []
            self.read_blocks: list[int] = []

        async def xadd(self, name, fields, **kwargs):
            entry_id = f"1700000000000-{len(self.entries)}"
            self.entries.append((entry_id, fields))
            assert name == agent_live_stream.live_stream_key("run-1")
            assert kwargs["maxlen"] == agent_live_stream.LIVE_STREAM_MAXLEN
            return entry_id

        async def expire(self, name, seconds):
            self.expirations.append((name, seconds))
            return True

        def pipeline(self, transaction=False):
            assert transaction is False
            redis = self

            class FakePipeline:
                def __init__(self) -> None:
                    self.commands = []

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, traceback):
                    return False

                def xadd(self, *args, **kwargs):
                    self.commands.append(("xadd", args, kwargs))

                def expire(self, *args, **kwargs):
                    self.commands.append(("expire", args, kwargs))

                async def execute(self):
                    results = []
                    for name, args, kwargs in self.commands:
                        results.append(await getattr(redis, name)(*args, **kwargs))
                    return results

            return FakePipeline()

        async def xread(self, streams, **kwargs):
            self.read_blocks.append(kwargs["block"])
            name, cursor = next(iter(streams.items()))
            return [
                (
                    name,
                    [entry for entry in self.entries if entry[0] > cursor],
                )
            ]

        async def aclose(self):
            return None

    async def assert_round_trip() -> None:
        fake = FakeRedis()
        original_client = agent_live_stream._redis_client
        agent_live_stream._redis_client = lambda _settings: fake
        try:
            publisher = agent_live_stream.AgentLiveStreamPublisher(
                settings(),
                "run-1",
            )
            await publisher.publish({"type": "process", "event": {}})
            await publisher.publish(
                {
                    "type": "answer_delta",
                    "delta": "hello",
                    "stream_epoch": "worker-1",
                }
            )
            await publisher.publish(
                {
                    "type": "reasoning_delta",
                    "delta": "thinking",
                    "stream_epoch": "worker-1",
                }
            )
            await publisher.publish(
                {
                    "type": "answer_reset",
                    "stream_epoch": "worker-1",
                }
            )
            reader = agent_live_stream.AgentLiveStreamReader(settings(), "run-1")
            events = await reader.read(
                "0-0",
                agent_live_stream.LIVE_STREAM_MAX_BLOCK_MS + 1000,
            )
            await publisher.close()
            await reader.close()
        finally:
            agent_live_stream._redis_client = original_client
        assert events == [
            (
                "1700000000000-0",
                {
                    "type": "answer_delta",
                    "delta": "hello",
                    "stream_epoch": "worker-1",
                },
            ),
            (
                "1700000000000-1",
                {
                    "type": "reasoning_delta",
                    "delta": "thinking",
                    "stream_epoch": "worker-1",
                },
            ),
            (
                "1700000000000-2",
                {
                    "type": "answer_reset",
                    "stream_epoch": "worker-1",
                },
            ),
        ]
        assert fake.expirations == [
            (
                agent_live_stream.live_stream_key("run-1"),
                agent_live_stream.LIVE_STREAM_TTL_SECONDS,
            ),
            (
                agent_live_stream.live_stream_key("run-1"),
                agent_live_stream.LIVE_STREAM_TTL_SECONDS,
            ),
            (
                agent_live_stream.live_stream_key("run-1"),
                agent_live_stream.LIVE_STREAM_TTL_SECONDS,
            ),
        ]
        assert fake.read_blocks == [agent_live_stream.LIVE_STREAM_MAX_BLOCK_MS]

    asyncio.run(assert_round_trip())

def test_mcp_private_network_policy() -> None:
    from app.adapters.mcp.client import (
        McpClientError,
        validate_mcp_destination,
    )

    asyncio.run(validate_mcp_destination("http://8.8.8.8/mcp", False))
    asyncio.run(validate_mcp_destination("http://127.0.0.1:8081/sse", True))
    try:
        asyncio.run(validate_mcp_destination("http://127.0.0.1:8081/sse", False))
    except McpClientError as exc:
        assert str(exc) == "Private MCP server addresses are not allowed."
    else:
        raise AssertionError("Private MCP address was accepted without opt-in")

def test_mcp_stdio_configuration() -> None:
    import os
    import sys

    from app.infra.tools.mcp_stdio import (
        McpStdioConfigError,
        parse_mcp_stdio_config,
        serialize_mcp_stdio_config,
        validate_mcp_stdio_config_runtime,
    )

    config = parse_mcp_stdio_config(
        {
            "command": sys.executable,
            "args": ["-m", "tests.unit"],
            "cwd": os.getcwd(),
            "env": {"NEXAFLOW_TEST_SECRET": "configured-in-form"},
        }
    )
    assert config.args == ("-m", "tests.unit")
    assert dict(config.env) == {"NEXAFLOW_TEST_SECRET": "configured-in-form"}
    assert parse_mcp_stdio_config(serialize_mcp_stdio_config(config)) == config
    validate_mcp_stdio_config_runtime(config)

    for invalid in (
        {"command": "relative-command"},
        {"command": sys.executable, "shell": True},
        {"command": sys.executable, "env": {"BAD=NAME": "value"}},
        {"command": sys.executable, "env": {"KEY": "bad\0value"}},
    ):
        try:
            parse_mcp_stdio_config(invalid)
        except McpStdioConfigError:
            continue
        raise AssertionError(f"Invalid stdio configuration accepted: {invalid}")

def test_mcp_server_create_request_transport_matrix() -> None:
    from pydantic import ValidationError

    from app.schemas.tools.mcp import McpServerCreateRequest

    compatible = McpServerCreateRequest(
        name="Existing client",
        url="https://tools.example.com/mcp",
    )
    assert compatible.transport == "streamable_http"
    assert compatible.stdio_config is None

    sse = McpServerCreateRequest(
        name="Legacy SSE",
        transport="sse",
        url="https://tools.example.com/sse/",
        bearer_token="token",
    )
    assert sse.url == "https://tools.example.com/sse/"

    stdio = McpServerCreateRequest(
        name="Local",
        transport="stdio",
        stdio_config={"command": "/usr/bin/python3"},
    )
    assert stdio.url is None
    assert stdio.stdio_config is not None

    invalid_payloads = (
        {"name": "Missing URL", "transport": "sse"},
        {
            "name": "Remote profile",
            "url": "https://tools.example.com/mcp",
            "stdio_config": {"command": "/usr/bin/python3"},
        },
        {
            "name": "stdio URL",
            "transport": "stdio",
            "stdio_config": {"command": "/usr/bin/python3"},
            "url": "https://tools.example.com/mcp",
        },
        {
            "name": "stdio command",
            "transport": "stdio",
            "stdio_config": {"command": "/usr/bin/python3"},
            "command": "/bin/sh",
        },
        {
            "name": "legacy stdio profile",
            "transport": "stdio",
            "stdio_profile": "local-test",
        },
    )
    for payload in invalid_payloads:
        try:
            McpServerCreateRequest.model_validate(payload)
        except ValidationError:
            continue
        raise AssertionError(f"Invalid MCP server payload accepted: {payload}")


def main() -> None:
    test_effective_agent_permission_matrix()
    test_tool_ref_requires_stable_ids()
    test_agent_publication_snapshot_is_canonical_and_tool_versioned()
    test_agent_runtime_snapshots_are_versioned_and_fail_closed()
    test_agent_tool_binding_requires_current_available_policy()
    test_tool_snapshot_is_an_immutable_internal_contract()
    test_tool_contracts_deep_freeze_nested_json()
    test_freeze_json_rejects_non_json_values()
    test_tool_adapter_contract_is_provider_neutral()
    test_agent_tool_definition_comes_from_unified_snapshot()
    test_agent_tool_runtime_uses_stable_invocation_identity_and_envelope()
    test_agent_tool_call_migration_preserves_approval_gate()
    test_unified_agent_runs_use_a_worker_generation_fence()
    test_tool_invocation_identity_ignores_refreshable_deadline()
    test_public_tool_responses_exclude_execution_details()
    test_validate_agent_permission_only_accepts_view()
    test_safe_agent_error_classification()
    test_agent_process_events_update_in_place()
    test_agent_event_replay_reads_every_page()
    test_stale_mcp_policy_requires_approval()
    test_external_mcp_policy_public_reconciles_like_console()
    test_external_mcp_policy_drift_requires_public_approval_but_blocks_api()
    test_external_stream_epoch_is_stable_and_sanitized()
    test_external_progress_events_carry_knowledge_hits()
    test_external_progress_events_carry_mcp_tool_details()
    test_external_progress_events_bound_tool_inputs_and_pass_output()
    test_external_progress_events_knowledge_failure_has_no_hits()
    test_external_progress_events_include_grounding_stage()
    test_mcp_policy_concurrent_first_write_reloads_existing()
    test_mcp_function_name_is_stable_and_sanitized()
    test_run_to_response_maps_run_fields()
    test_run_response_normalizes_legacy_source_links()
    test_regenerated_agent_run_starts_from_a_fresh_checkpoint()
    test_edit_regeneration_rejects_a_non_latest_run()
    test_repeated_run_feedback_write_is_idempotent()
    test_agent_usage_normalizes_provider_metadata()
    test_knowledge_context_is_compact_for_repeated_model_turns()
    test_agent_memory_compacts_old_turns()
    test_agent_memory_query_is_bounded_and_projected()
    test_mcp_server_to_response()
    test_unified_mcp_policy_projection_fails_closed_and_honors_kill_switch()
    test_agent_live_stream_round_trip()
    test_mcp_private_network_policy()
    test_mcp_stdio_configuration()
    test_mcp_server_create_request_transport_matrix()
    print("AGENTS_UNIT_OK")


if __name__ == "__main__":
    main()
