"""Pure unit tests for the workflows feature (moved from the former tests/unit.py).

No database, no HTTP client, no network: repositories and capability ports
are mocked or monkeypatched so each unit is tested in isolation. Run from
``backend/`` with:

    uv run python -m tests.workflows.unit
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

def test_workflow_uses_canonical_tool_refs_and_inline_python_builtin() -> None:
    from app.schemas.workflows.contracts import LlmNodeConfig, ToolNodeConfig
    from app.domain.tools.catalog.service import build_inline_python_tool

    reference = {"tool_id": "tool-1", "version_id": "version-1"}
    node = ToolNodeConfig.model_validate(
        {"tool": reference, "arguments": {"value": "{{start.question}}"}}
    )
    llm = LlmNodeConfig.model_validate(
        {"prompt": "Use a tool", "tools": [reference]}
    )
    assert node.tool.model_dump() == reference
    assert [item.model_dump() for item in llm.tools] == [reference]

    tool, version, policy = build_inline_python_tool("workspace-1")
    assert tool.stable_key == "inline_python"
    assert tool.current_version_id == version.id
    assert version.execution_spec == {
        "builtin": "inline_python",
        "workflow_only": True,
        "direct_only": True,
    }
    assert policy.approval == "auto"
    assert policy.effect == "pure"
    assert policy.workflow_callable is True
    assert policy.parallel_safe is False

def test_workflow_legacy_tools_normalize_to_one_canonical_node_contract() -> None:
    from app.entities.tools import ToolRef
    from app.schemas.workflows.contracts import WorkflowGraph
    from app.domain.workflows.resources import (
        canonicalize_workflow_graph,
        workflow_resource_references,
    )

    graph = WorkflowGraph.model_validate(
        {
            "nodes": [
                {
                    "id": "remote",
                    "type": "workflow",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "mcp",
                        "title": "Remote",
                        "config": {
                            "server_id": "server-1",
                            "tool_name": "lookup",
                            "arguments": {"query": "hello"},
                        },
                    },
                },
                {
                    "id": "python",
                    "type": "workflow",
                    "position": {"x": 0, "y": 100},
                    "data": {
                        "type": "code",
                        "title": "Python",
                        "config": {
                            "code": "result = inputs",
                            "inputs": {"value": 1},
                        },
                    },
                },
                {
                    "id": "model",
                    "type": "workflow",
                    "position": {"x": 0, "y": 200},
                    "data": {
                        "type": "llm",
                        "title": "Model",
                        "config": {
                            "prompt": "answer",
                            "mcp_enable": True,
                            "mcp_servers": [
                                {"server_id": "server-1", "tool_name": "lookup"}
                            ],
                        },
                    },
                },
            ],
            "edges": [],
        }
    )
    remote = ToolRef("tool-remote", "version-remote")
    inline = ToolRef("tool-inline", "version-inline")
    canonical = canonicalize_workflow_graph(
        graph,
        {("server-1", "lookup"): remote},
        inline,
    )

    assert [node.data.type for node in canonical.nodes] == ["tool", "tool", "llm"]
    assert canonical.nodes[0].data.config == {
        "tool": {"tool_id": "tool-remote", "version_id": "version-remote"},
        "arguments": {"query": "hello"},
    }
    assert canonical.nodes[1].data.config == {
        "tool": {"tool_id": "tool-inline", "version_id": "version-inline"},
        "arguments": {"code": "result = inputs", "inputs": {"value": 1}},
    }
    assert canonical.nodes[2].data.config["tools"] == [
        {"tool_id": "tool-remote", "version_id": "version-remote"}
    ]
    assert "mcp_enable" not in canonical.nodes[2].data.config
    assert workflow_resource_references(canonical)[1] == [remote, inline]

def test_workflow_selects_only_exact_bound_tool_versions() -> None:
    from app.entities.tools import ToolRef, ToolSnapshot
    from app.domain.workflows.resources import select_tool_snapshots

    def snapshot(tool_id: str, version_id: str) -> ToolSnapshot:
        return ToolSnapshot(
            schema_version=1,
            tool_id=tool_id,
            version_id=version_id,
            source_id="source-1",
            kind="python",
            function_name=tool_id,
            display_name=tool_id,
            description="",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={"type": "object", "additionalProperties": False},
            definition_hash=f"hash-{version_id}",
            policy_id=f"policy-{tool_id}",
            policy_revision=1,
            bound_by_user_id="binder-1",
            approval="auto",
            effect="pure",
            allowed_access_sources=("console",),
            workflow_callable=True,
            parallel_safe=False,
            execution_spec={"code": "result = {}"},
        )

    selected = select_tool_snapshots(
        [ToolRef("tool-b", "version-b")],
        [snapshot("tool-a", "version-a"), snapshot("tool-b", "version-b")],
    )
    assert [(item.tool_id, item.bound_by_user_id) for item in selected] == [
        ("tool-b", "binder-1")
    ]

    for reference in (
        ToolRef("missing", "version-1"),
        ToolRef("tool-b", "version-other"),
    ):
        try:
            select_tool_snapshots(
                [reference],
                [snapshot("tool-b", "version-b")],
            )
        except ValueError:
            continue
        raise AssertionError("Unbound Workflow Tool version was accepted.")

def test_workflow_resource_snapshot_must_match_the_canonical_graph() -> None:
    from app.entities.tools import ToolRef, ToolSnapshot
    from app.schemas.workflows.contracts import WorkflowGraph
    from app.domain.workflows.resources import (
        build_workflow_resource_snapshot,
        load_workflow_resource_snapshot,
        workflow_resource_hash,
    )

    reference = ToolRef("tool-1", "version-1")
    graph = WorkflowGraph.model_validate(
        {
            "nodes": [
                {
                    "id": "tool",
                    "type": "workflow",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "tool",
                        "title": "Tool",
                        "config": {
                            "tool": {
                                "tool_id": reference.tool_id,
                                "version_id": reference.version_id,
                            },
                            "arguments": {},
                        },
                    },
                }
            ],
            "edges": [],
        }
    )
    tool = ToolSnapshot(
        schema_version=1,
        tool_id=reference.tool_id,
        version_id=reference.version_id,
        source_id="source-1",
        kind="python",
        function_name="tool_1",
        display_name="Tool",
        description="",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object", "additionalProperties": False},
        definition_hash="hash-1",
        policy_id="policy-1",
        policy_revision=1,
        bound_by_user_id="binder-1",
        approval="auto",
        effect="pure",
        allowed_access_sources=("console",),
        workflow_callable=True,
        parallel_safe=False,
        execution_spec={"code": "result = {}"},
    )
    payload = build_workflow_resource_snapshot([], [tool])
    knowledge_ids, tools = load_workflow_resource_snapshot(
        graph,
        payload,
        workflow_resource_hash(payload),
    )
    assert knowledge_ids == []
    assert tools == [tool]

    for invalid in (
        {**payload, "legacy": True},
        {**payload, "tools": []},
    ):
        try:
            load_workflow_resource_snapshot(
                graph,
                invalid,
                workflow_resource_hash(invalid),
            )
        except ValueError:
            continue
        raise AssertionError("Invalid Workflow resource snapshot was accepted.")

def test_workflow_agent_nodes_pin_versions_and_cannot_run_in_parallel() -> None:
    from app.domain.workflows.runtime.engine import (
        WorkflowValidationError,
        validate_graph,
    )
    from app.domain.workflows.resources import (
        build_workflow_resource_snapshot,
        load_workflow_agent_snapshots,
        workflow_resource_hash,
    )

    def node(node_id: str, node_type: str, config: dict | None = None) -> dict:
        return {
            "id": node_id,
            "type": "workflow",
            "position": {"x": 0, "y": 0},
            "data": {
                "type": node_type,
                "title": node_id,
                "config": config or {},
            },
        }

    graph = validate_graph(
        {
            "nodes": [
                node("start", "start"),
                node(
                    "agent",
                    "agent",
                    {
                        "agent_id": "agent-1",
                        "agent_version_id": "version-1",
                        "input": "{{start.question}}",
                    },
                ),
                node("end", "end", {"outputs": {"result": "{{agent.result}}"}}),
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "agent"},
                {"id": "e2", "source": "agent", "target": "end"},
            ],
        }
    )
    agent_snapshot = {
        "agent_id": "agent-1",
        "version_id": "version-1",
        "version_number": 1,
        "configuration_hash": "hash-1",
        "configuration_snapshot": {"name": "Helper"},
        "resource_snapshot": {"knowledge_base_ids": [], "tools": []},
        "bound_by_user_id": "binder-1",
    }
    snapshot = build_workflow_resource_snapshot([], [], [agent_snapshot])
    assert load_workflow_agent_snapshots(
        graph,
        snapshot,
        workflow_resource_hash(snapshot),
    ) == [agent_snapshot]

    wrong_agent = build_workflow_resource_snapshot(
        [],
        [],
        [{**agent_snapshot, "agent_id": "agent-2"}],
    )
    try:
        load_workflow_agent_snapshots(
            graph,
            wrong_agent,
            workflow_resource_hash(wrong_agent),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Workflow Agent identity mismatch was accepted.")

    invalid = build_workflow_resource_snapshot([], [], [])
    try:
        load_workflow_agent_snapshots(
            graph,
            invalid,
            workflow_resource_hash(invalid),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Workflow Agent version missing from snapshot was accepted.")

    parallel_graph = {
        "nodes": [
            node("start", "start"),
            node(
                "agent_a",
                "agent",
                {"agent_id": "a1", "agent_version_id": "v1", "input": "a"},
            ),
            node(
                "agent_b",
                "agent",
                {"agent_id": "a2", "agent_version_id": "v2", "input": "b"},
            ),
            node("end", "end", {"outputs": {}}),
        ],
        "edges": [
            {"id": "a1", "source": "start", "target": "agent_a"},
            {"id": "a2", "source": "agent_a", "target": "end"},
            {"id": "b1", "source": "start", "target": "agent_b"},
            {"id": "b2", "source": "agent_b", "target": "end"},
        ],
    }
    try:
        validate_graph(parallel_graph)
    except WorkflowValidationError:
        pass
    else:
        raise AssertionError("Parallel Workflow Agent nodes were accepted.")

    oversized_graph = {
        "nodes": [
            node("start", "start"),
            node(
                "agent",
                "agent",
                {
                    "agent_id": "agent-1",
                    "agent_version_id": "version-1",
                    "input": "x" * (128 * 1024),
                },
            ),
            node("end", "end", {"outputs": {}}),
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "agent"},
            {"id": "e2", "source": "agent", "target": "end"},
        ],
    }
    try:
        validate_graph(oversized_graph)
    except WorkflowValidationError:
        pass
    else:
        raise AssertionError("Oversized Workflow Agent input was accepted.")

def test_workflow_tool_invocation_identity_is_stable_and_bounded() -> None:
    from app.application.workflows.tools.runtime import workflow_tool_invocation_identity
    from app.domain.tools.runtime import tool_arguments_hash

    first = workflow_tool_invocation_identity("run-1", "node-1", "call-1")
    second = workflow_tool_invocation_identity("run-1", "node-1", "call-1")
    assert first == second
    assert first[0] == "node-1:call-1"
    assert len(first[1]) == 64
    assert tool_arguments_hash({"a": 1, "nested": {"b": 2, "c": 3}}) == (
        tool_arguments_hash({"nested": {"c": 3, "b": 2}, "a": 1})
    )

    try:
        workflow_tool_invocation_identity("run-1", "n" * 200, "c" * 100)
    except ValueError:
        pass
    else:
        raise AssertionError("Oversized Workflow Tool identity was accepted.")

def test_workflow_tool_runtime_serializes_unsafe_tools_and_blocks_direct_only_llm() -> None:
    from app.application.workflows.tools.runtime import WorkflowToolRuntime
    from app.entities.tools import ToolSnapshot

    def snapshot(
        tool_id: str,
        *,
        parallel_safe: bool,
        direct_only: bool = False,
    ) -> ToolSnapshot:
        return ToolSnapshot(
            schema_version=1,
            tool_id=tool_id,
            version_id=f"version-{tool_id}",
            source_id="source-1",
            kind="builtin",
            function_name=tool_id,
            display_name=tool_id,
            description="",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            definition_hash=f"hash-{tool_id}",
            policy_id=f"policy-{tool_id}",
            policy_revision=1,
            bound_by_user_id="user-1",
            approval="auto",
            effect="pure",
            allowed_access_sources=("console",),
            workflow_callable=True,
            parallel_safe=parallel_safe,
            execution_spec={"direct_only": direct_only},
        )

    serial = snapshot("serial", parallel_safe=False)
    parallel = snapshot("parallel", parallel_safe=True)
    direct_only = snapshot("direct", parallel_safe=True, direct_only=True)
    runtime = WorkflowToolRuntime(
        SimpleNamespace(),
        SimpleNamespace(),
        [serial, parallel, direct_only],
        "worker-1",
        SimpleNamespace(),
        asyncio.Event(),
    )
    active = 0
    maximum = 0

    async def fake_invoke(_snapshot, _node_id, _call_id, _arguments):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return SimpleNamespace(is_error=False)

    runtime._invoke = fake_invoke  # type: ignore[method-assign]

    async def assert_runtime_contract() -> None:
        nonlocal maximum
        await asyncio.gather(
            runtime.invoke(serial, "node-1", "direct", {}),
            runtime.invoke(serial, "node-2", "direct", {}),
        )
        assert maximum == 1
        maximum = 0
        await asyncio.gather(
            runtime.invoke(parallel, "node-1", "direct", {}),
            runtime.invoke(parallel, "node-2", "direct", {}),
        )
        assert maximum == 2
        try:
            await runtime.invoke(direct_only, "node-3", "llm:1:direct", {})
        except RuntimeError:
            pass
        else:
            raise AssertionError("Direct-only Workflow Tool was exposed to an LLM.")

    asyncio.run(assert_runtime_contract())

def test_workflow_tool_migration_matches_runtime_catalog() -> None:
    import importlib.util
    from datetime import UTC, datetime
    from pathlib import Path

    import sqlalchemy as sa

    from app.domain.tools.catalog.service import build_inline_python_tool

    path = (
        Path(__file__).parents[2]
        / "alembic/versions/202608170002_workflow_tool_resources.py"
    )
    spec = importlib.util.spec_from_file_location("workflow_tool_resources", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    created_at = datetime(2026, 8, 17, tzinfo=UTC)
    source, migrated_tool, migrated_version, migrated_policy = (
        migration._inline_python_rows("workspace-1", created_at)
    )
    tool, version, policy = build_inline_python_tool("workspace-1", created_at)
    assert source["name"] == "Built-in"
    assert migrated_tool["id"] == tool.id
    assert migrated_tool["function_name"] == tool.function_name
    # The historical migration remains immutable; the Skills contract is
    # published by the follow-up migration and therefore has a new version.
    assert migrated_version["id"] != version.id
    assert migrated_version["definition_hash"] != version.definition_hash
    assert "skills" in version.input_schema["properties"]
    assert migrated_policy["id"] == policy.id
    assert migrated_policy["tool_version_id"] != policy.tool_version_id

    graph = {
        "nodes": [
            {
                "data": {
                    "type": "knowledge",
                    "config": {"knowledge_base_ids": ["kb-1", "kb-1"]},
                }
            },
            {
                "data": {
                    "type": "mcp",
                    "config": {"server_id": "server-1", "tool_name": "lookup"},
                }
            },
            {"data": {"type": "code", "config": {"code": "result = {}"}}},
            {
                "data": {
                    "type": "llm",
                    "config": {
                        "tools": [
                            {"tool_id": "tool-1", "version_id": "version-1"}
                        ]
                    },
                }
            },
        ]
    }
    assert migration._graph_references(graph) == (
        ["kb-1"],
        [("server-1", "lookup")],
        [("tool-1", "version-1")],
        True,
    )
    assert migration._graph_has_canonical_tool_reference(graph)
    assert migration._graph_has_canonical_tool_reference(
        {"nodes": [{"data": {"type": "tool", "config": {}}}]}
    )

    metadata = sa.MetaData()
    tools = sa.Table(
        "tools",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("stable_key", sa.String, nullable=False),
        sa.Column("current_version_id", sa.String),
    )
    definitions = sa.Table(
        "workflow_definitions",
        metadata,
        sa.Column("workspace_id", sa.String, nullable=False),
        sa.Column("agent_id", sa.String, nullable=False),
        sa.Column("graph", sa.JSON, nullable=False),
        sa.Column("updated_by_user_id", sa.String, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    bindings = sa.Table(
        "application_tool_bindings",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, nullable=False),
        sa.Column("application_id", sa.String, nullable=False),
        sa.Column("tool_id", sa.String, nullable=False),
        sa.Column("tool_version_id", sa.String, nullable=False),
        sa.Column("bound_by_user_id", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            tools.insert(),
            {
                "id": migrated_tool["id"],
                "workspace_id": "workspace-1",
                "kind": "builtin",
                "stable_key": "inline_python",
                "current_version_id": migrated_version["id"],
            },
        )
        connection.execute(
            definitions.insert(),
            {
                "workspace_id": "workspace-1",
                "agent_id": "workflow-1",
                "graph": {
                    "nodes": [
                        {
                            "data": {
                                "type": "code",
                                "config": {"code": "result = {}"},
                            }
                        }
                    ]
                },
                "updated_by_user_id": "user-1",
                "updated_at": created_at,
            },
        )
        migration._backfill_inline_python_bindings(connection)
        migration._backfill_inline_python_bindings(connection)
        rows = connection.execute(sa.select(bindings)).mappings().all()
        assert len(rows) == 1
        assert rows[0]["application_id"] == "workflow-1"
        assert rows[0]["tool_version_id"] == migrated_version["id"]


def main() -> None:
    test_workflow_uses_canonical_tool_refs_and_inline_python_builtin()
    test_workflow_legacy_tools_normalize_to_one_canonical_node_contract()
    test_workflow_selects_only_exact_bound_tool_versions()
    test_workflow_resource_snapshot_must_match_the_canonical_graph()
    test_workflow_agent_nodes_pin_versions_and_cannot_run_in_parallel()
    test_workflow_tool_invocation_identity_is_stable_and_bounded()
    test_workflow_tool_runtime_serializes_unsafe_tools_and_blocks_direct_only_llm()
    test_workflow_tool_migration_matches_runtime_catalog()
    print("WORKFLOWS_UNIT_OK")


if __name__ == "__main__":
    main()
