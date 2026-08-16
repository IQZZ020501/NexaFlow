"""Unified Tool persistence and migration regression suite.

Run from ``backend/`` with:

    uv run python -m tests.tools
"""

import asyncio
from dataclasses import asdict, fields
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

from tests.support import activate_admin, test_client

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.infrastructure.session import get_session_factory


EXPECTED_COLUMNS = {
    "ToolSource": (
        "id",
        "workspace_id",
        "mcp_server_id",
        "kind",
        "name",
        "status",
        "created_by_user_id",
        "created_at",
        "updated_at",
    ),
    "Tool": (
        "id",
        "workspace_id",
        "source_id",
        "kind",
        "stable_key",
        "function_name",
        "current_version_id",
        "status",
        "availability",
        "created_by_user_id",
        "created_at",
        "updated_at",
    ),
    "ToolDraft": (
        "id",
        "workspace_id",
        "tool_id",
        "display_name",
        "description",
        "input_schema",
        "output_schema",
        "execution_spec",
        "revision",
        "updated_by_user_id",
        "created_at",
        "updated_at",
    ),
    "ToolVersion": (
        "id",
        "workspace_id",
        "tool_id",
        "revision",
        "display_name",
        "description",
        "input_schema",
        "output_schema",
        "execution_spec",
        "definition_hash",
        "created_by_user_id",
        "created_at",
    ),
    "ToolPolicy": (
        "id",
        "workspace_id",
        "tool_id",
        "tool_version_id",
        "definition_hash",
        "revision",
        "approval",
        "effect",
        "allowed_access_sources",
        "workflow_callable",
        "parallel_safe",
        "reviewed_by_user_id",
        "reviewed_at",
        "created_at",
        "updated_at",
    ),
    "ApplicationToolBinding": (
        "id",
        "workspace_id",
        "application_id",
        "tool_id",
        "tool_version_id",
        "bound_by_user_id",
        "created_at",
    ),
    "ToolInvocation": (
        "id",
        "workspace_id",
        "origin",
        "root_run_id",
        "run_id",
        "invocation_id",
        "execution_user_id",
        "access_source",
        "tool_id",
        "tool_version_id",
        "policy_snapshot",
        "arguments",
        "arguments_hash",
        "idempotency_key",
        "status",
        "attempts",
        "max_attempts",
        "approved_by_user_id",
        "approved_at",
        "worker_task_id",
        "lease_expires_at",
        "result_data",
        "result_summary",
        "outcome",
        "error_code",
        "error_message",
        "usage",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    ),
}


def run(coro):
    return asyncio.run(coro)


def load_migration():
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/202608160003_unified_tool_persistence.py"
    )
    spec = spec_from_file_location("unified_tool_persistence", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def constraint_sql(table, name: str) -> str:
    constraint = next(item for item in table.constraints if item.name == name)
    assert isinstance(constraint, CheckConstraint)
    return str(constraint.sqltext)


def foreign_key_columns(table) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def unique_columns(table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_stable_catalog_contract_matches_legacy_mcp_identity() -> None:
    from app.shareddomain.tools.catalog import (
        build_workspace_system_catalog,
        mcp_definition_hash,
        mcp_function_name,
        stable_catalog_id,
    )

    definition = {
        "name": "order items!",
        "description": "Lookup an order.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    }
    assert (
        stable_catalog_id("source:workspace-1:builtin")
        == "b2a73177-a839-597c-9b17-37a3f9eb0200"
    )
    assert (
        stable_catalog_id("tool:workspace-1:mcp:server-1:order items!")
        == "6f168232-2888-5d58-b984-ab813fbf18c6"
    )
    assert (
        mcp_definition_hash(definition)
        == "a209eb01cc7d06a744bdcf7d7114b9d3b082f991facb0d6ed85fdc79d252f335"
    )
    assert mcp_function_name("server-1", "order items!") == (
        "mcp_order_items_bd4a7707"
    )

    migration = load_migration()
    assert migration.revision == "202608160003"
    assert migration.down_revision == "202608160002"
    assert migration._stable_catalog_id("source:workspace-1:builtin") == (
        "b2a73177-a839-597c-9b17-37a3f9eb0200"
    )
    assert migration._mcp_definition_hash(definition) == mcp_definition_hash(
        definition
    )
    assert migration._mcp_function_name("server-1", "order items!") == (
        "mcp_order_items_bd4a7707"
    )

    timestamp = datetime(2026, 8, 16, tzinfo=UTC)
    catalog = build_workspace_system_catalog("workspace-1", timestamp)
    source_rows, tool_row, version_row, policy_row = migration._system_catalog_rows(
        "workspace-1", timestamp
    )
    tool_row["current_version_id"] = version_row["id"]
    assert source_rows == [asdict(source) for source in catalog.sources]
    assert tool_row == asdict(catalog.tool)
    assert version_row == asdict(catalog.version)
    assert policy_row == asdict(catalog.policy)


def test_migration_collects_policy_only_tools_deterministically() -> None:
    migration = load_migration()
    references = {}
    servers = {
        ("workspace-1", "server-1"): {
            "workspace_id": "workspace-1",
            "id": "server-1",
            "status": "active",
            "created_by_user_id": "owner-b",
        }
    }
    policies = [
        {
            "workspace_id": "workspace-1",
            "mcp_server_id": "server-1",
            "tool_name": "policy-only",
        }
    ]
    migration._add_legacy_policy_references(references, policies, servers)
    migration._add_reference(
        references,
        "workspace-1",
        "server-1",
        "policy-only",
        "owner-a",
    )
    migration._add_reference(
        references,
        "workspace-1",
        "server-1",
        "policy-only",
        None,
    )
    assert references == {
        ("workspace-1", "server-1", "policy-only"): "owner-a"
    }
    assert migration._mcp_tool_available({"name": "policy-only"}, servers[
        ("workspace-1", "server-1")
    ])
    disabled = {**servers[("workspace-1", "server-1")], "status": "disabled"}
    assert not migration._mcp_tool_available({"name": "policy-only"}, disabled)


def test_entities_and_orm_columns_match_exactly() -> None:
    from app.entities import tools as entities
    from app.shareddomain.tools import models

    expected_tables = {
        "ToolSource": "tool_sources",
        "Tool": "tools",
        "ToolDraft": "tool_drafts",
        "ToolVersion": "tool_versions",
        "ToolPolicy": "tool_policies",
        "ApplicationToolBinding": "application_tool_bindings",
        "ToolInvocation": "tool_invocations",
    }
    for class_name, column_names in EXPECTED_COLUMNS.items():
        entity = getattr(entities, class_name)
        orm = getattr(models, class_name)
        assert tuple(field.name for field in fields(entity)) == column_names
        assert tuple(orm.__table__.columns.keys()) == column_names
        assert orm.__tablename__ == expected_tables[class_name]

    assert entities.ToolSource(kind="builtin").created_by_user_id is None
    assert entities.Tool(kind="builtin").created_by_user_id is None
    assert entities.ToolInvocation(origin="test").execution_user_id == ""


def test_orm_enforces_tenant_scoped_relations_and_legal_states() -> None:
    from app.domain.resource_permission import ResourcePermission
    from app.shareddomain.tools.models import (
        ApplicationToolBinding,
        Tool,
        ToolDraft,
        ToolInvocation,
        ToolPolicy,
        ToolSource,
        ToolVersion,
    )

    assert (("workspace_id", "source_id"), (
        "tool_sources.workspace_id",
        "tool_sources.id",
    )) in foreign_key_columns(Tool.__table__)
    assert (("workspace_id", "mcp_server_id"), (
        "mcp_servers.workspace_id",
        "mcp_servers.id",
    )) in foreign_key_columns(ToolSource.__table__)
    assert (("workspace_id", "id", "current_version_id"), (
        "tool_versions.workspace_id",
        "tool_versions.tool_id",
        "tool_versions.id",
    )) in foreign_key_columns(Tool.__table__)
    assert (("workspace_id", "tool_id"), (
        "tools.workspace_id",
        "tools.id",
    )) in foreign_key_columns(ToolDraft.__table__)
    assert (("workspace_id", "tool_id", "tool_version_id"), (
        "tool_versions.workspace_id",
        "tool_versions.tool_id",
        "tool_versions.id",
    )) in foreign_key_columns(ToolPolicy.__table__)
    assert (("workspace_id", "application_id"), (
        "agents.workspace_id",
        "agents.id",
    )) in foreign_key_columns(ApplicationToolBinding.__table__)
    assert (("workspace_id", "run_id"), (
        "agent_runs.workspace_id",
        "agent_runs.id",
    )) in foreign_key_columns(ToolInvocation.__table__)
    assert (("workspace_id", "root_run_id"), (
        "agent_runs.workspace_id",
        "agent_runs.id",
    )) in foreign_key_columns(ToolInvocation.__table__)

    assert ("workspace_id", "id") in unique_columns(ToolSource.__table__)
    assert ("workspace_id", "function_name") in unique_columns(Tool.__table__)
    assert ("source_id", "stable_key") in unique_columns(Tool.__table__)
    assert ("workspace_id", "tool_id", "id") in unique_columns(
        ToolVersion.__table__
    )
    assert ("workspace_id", "idempotency_key") in unique_columns(
        ToolInvocation.__table__
    )
    source_kind_sql = constraint_sql(
        ToolSource.__table__, "ck_tool_sources_mcp_server_kind"
    )
    assert "mcp_server_id IS NOT NULL" in source_kind_sql
    assert "mcp_server_id IS NULL AND status = 'archived'" in source_kind_sql
    assert "kind IN ('builtin', 'python') AND mcp_server_id IS NULL" in (
        source_kind_sql
    )

    permission_sql = constraint_sql(
        ResourcePermission.__table__,
        "ck_resource_permissions_type_permission",
    )
    for allowed in (
        "resource_type = 'knowledge_base'",
        "permission IN ('view', 'edit')",
        "resource_type = 'agent'",
        "permission = 'view'",
        "resource_type = 'tool'",
        "permission IN ('view', 'use')",
    ):
        assert allowed in permission_sql
    origin_sql = constraint_sql(
        ToolInvocation.__table__, "ck_tool_invocations_origin_runs"
    )
    assert "origin = 'test'" in origin_sql
    assert "root_run_id IS NULL" in origin_sql
    assert "run_id IS NULL" in origin_sql


def test_tool_versions_are_immutable_at_repository_boundary() -> None:
    from app.entities.tools import ToolVersion
    from app.infrastructure.repositories import tools as repository

    version = ToolVersion(id="version-1", workspace_id="workspace-1", tool_id="tool-1")
    db = SimpleNamespace(
        get=lambda *_args: None,
    )

    async def existing(*_args):
        return SimpleNamespace(id="version-1")

    db.get = existing
    try:
        run(repository.save_tool_version(db, version))
    except ValueError as exc:
        assert "immutable" in str(exc).lower()
    else:
        raise AssertionError("An existing ToolVersion was updated in place.")


def test_migration_reference_scanner_keeps_historical_mcp_tuples() -> None:
    migration = load_migration()
    value = {
        "mcp_tools": [
            {"server_id": "server-a", "tool_name": "search"},
            {"server_id": "server-a", "tool_name": "search"},
        ],
        "nodes": [
            {
                "data": {
                    "type": "mcp",
                    "config": {
                        "server_id": "server-b",
                        "tool_name": "write",
                        "arguments": {},
                    },
                }
            },
            {
                "data": {
                    "type": "llm",
                    "config": {
                        "mcp_servers": [
                            {"server_id": "server-c", "tool_name": "lookup"}
                        ]
                    },
                }
            },
        ],
    }
    assert migration._extract_mcp_references(value) == {
        ("server-a", "search"),
        ("server-b", "write"),
        ("server-c", "lookup"),
    }


async def assert_workspace_system_catalog(workspace_id: str) -> None:
    from app.infrastructure.repositories import tools as repository

    async with get_session_factory()() as db:
        sources = await repository.list_tool_sources(db, workspace_id)
        assert [(source.kind, source.created_by_user_id) for source in sources] == [
            ("builtin", None),
            ("python", None),
        ]
        tools = await repository.list_tools(db, workspace_id)
        assert len(tools) == 1
        tool = tools[0]
        assert tool.stable_key == "current_time"
        assert tool.availability == "available"
        assert tool.current_version_id is not None
        version = await repository.get_tool_version(
            db, workspace_id, tool.current_version_id
        )
        policy = await repository.get_tool_policy(db, workspace_id, tool.id)
        assert version is not None
        assert policy is not None
        assert policy.tool_version_id == version.id
        assert policy.definition_hash == version.definition_hash
        assert policy.approval == "auto"
        assert policy.effect == "pure"


def test_workspace_creation_initializes_system_catalog() -> None:
    with test_client() as client:
        _token, workspace_id = activate_admin(client)
        run(assert_workspace_system_catalog(workspace_id))


def main() -> None:
    test_stable_catalog_contract_matches_legacy_mcp_identity()
    test_migration_collects_policy_only_tools_deterministically()
    test_entities_and_orm_columns_match_exactly()
    test_orm_enforces_tenant_scoped_relations_and_legal_states()
    test_tool_versions_are_immutable_at_repository_boundary()
    test_migration_reference_scanner_keeps_historical_mcp_tuples()
    test_workspace_creation_initializes_system_catalog()
    print("TOOLS_SUITE_OK")


if __name__ == "__main__":
    main()
