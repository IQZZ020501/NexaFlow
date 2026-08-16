"""Unified Tool persistence and migration regression suite.

Run from ``backend/`` with:

    uv run python -m tests.tools
"""

import asyncio
import random
from dataclasses import asdict, fields
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

from tests.support import (
    activate_admin,
    auth_headers,
    create_active_user,
    test_client,
)

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    MetaData,
    Table,
    UniqueConstraint,
)

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


def add_workspace_member(
    client,
    admin_token: str,
    workspace_id: str,
    user_id: str,
    role: str = "member",
) -> None:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members",
        headers=auth_headers(admin_token),
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 201, response.text


async def seed_private_tool(
    workspace_id: str,
    owner_id: str,
    stable_key: str,
):
    from app.entities.tools import Tool, ToolVersion
    from app.infrastructure.repositories import tools as tool_repository

    async with get_session_factory()() as db:
        sources = await tool_repository.list_tool_sources(db, workspace_id)
        python_source = next(source for source in sources if source.kind == "python")
        tool = await tool_repository.save_tool(
            db,
            Tool(
                workspace_id=workspace_id,
                source_id=python_source.id,
                kind="python",
                stable_key=stable_key,
                function_name=stable_key,
                created_by_user_id=owner_id,
            ),
        )
        version = await tool_repository.save_tool_version(
            db,
            ToolVersion(
                workspace_id=workspace_id,
                tool_id=tool.id,
                revision=1,
                display_name=stable_key,
                input_schema={"type": "object"},
                execution_spec={"code": "result = {}"},
                definition_hash=(stable_key.encode().hex() + "0" * 64)[:64],
                created_by_user_id=owner_id,
            ),
        )
        tool.current_version_id = version.id
        tool = await tool_repository.save_tool(db, tool)
        await db.commit()
        return tool, version


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


def load_network_policy_migration():
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/202608160004_mcp_network_policy.py"
    )
    spec = spec_from_file_location("mcp_network_policy", path)
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


def test_mcp_network_policy_migration_is_reversible_and_defaults_legacy() -> None:
    from app.entities.tools import McpServer as McpServerEntity
    from app.shareddomain.tools.models import McpServer

    migration = load_network_policy_migration()
    assert migration.revision == "202608160004"
    assert migration.down_revision == "202608160003"
    column = McpServer.__table__.c.network_policy
    assert column.nullable is False
    assert column.server_default is not None
    assert column.server_default.arg == "public_only"
    assert McpServerEntity().network_policy == "public_only"
    assert "public_only" in constraint_sql(
        McpServer.__table__,
        "ck_mcp_servers_network_policy",
    )

    calls: list[tuple] = []
    migration.op = SimpleNamespace(
        add_column=lambda *args: calls.append(("add_column", *args)),
        create_check_constraint=lambda *args: calls.append(("create_check", *args)),
        alter_column=lambda *args, **kwargs: calls.append(
            ("alter_column", *args, kwargs)
        ),
        drop_constraint=lambda *args, **kwargs: calls.append(
            ("drop_constraint", *args, kwargs)
        ),
        create_foreign_key=lambda *args, **kwargs: calls.append(
            ("create_foreign_key", *args, kwargs)
        ),
        drop_column=lambda *args: calls.append(("drop_column", *args)),
    )
    migration.upgrade()
    added = calls[0][2]
    assert added.name == "network_policy"
    assert added.nullable is False
    assert added.server_default.arg == "deployment"
    assert calls[1][0] == "create_check"
    assert calls[2][0] == "alter_column"
    assert calls[2][-1]["server_default"] == "public_only"
    assert calls[3][:3] == (
        "drop_constraint",
        "fk_resource_permission_workspace_user",
        "resource_permissions",
    )
    assert calls[4][0] == "create_foreign_key"
    assert calls[4][-1]["ondelete"] == "CASCADE"
    calls.clear()
    migration.downgrade()
    assert [call[0] for call in calls] == [
        "drop_constraint",
        "create_foreign_key",
        "drop_constraint",
        "drop_column",
    ]
    assert calls[1][-1].get("ondelete") is None


def test_legacy_disabled_tools_remain_disabled_after_backfill() -> None:
    migration = load_migration()
    active = {"status": "active"}
    disabled = {"status": "disabled"}
    assert migration._legacy_tool_status(active, "disabled") == "disabled"
    assert migration._legacy_tool_status(disabled, "read_only") == "disabled"
    assert migration._legacy_tool_status(active, "read_only") == "active"
    assert migration._legacy_tool_status(None, "read_only") == "archived"


def test_mcp_function_name_candidates_extend_stable_digest_on_collision() -> None:
    from app.shareddomain.tools.catalog import mcp_function_name_candidates

    candidates = mcp_function_name_candidates("server-1", "order items!")
    assert candidates[:3] == (
        "mcp_order_items_bd4a7707",
        "mcp_order_items_bd4a77076205",
        "mcp_order_items_bd4a770762057d62",
    )
    assert len(candidates[-1].rsplit("_", 1)[-1]) == 64


def test_resolved_mcp_tool_preserves_catalog_function_name() -> None:
    from mcp.types import Tool as McpTool

    from app.application.agent_tools import mcp_function_name
    from app.entities.tools import McpServer
    from app.shareddomain.tools.services import ResolvedMcpTool

    resolved = ResolvedMcpTool(
        server=McpServer(id="server-1", workspace_id="workspace-1"),
        definition=McpTool(name="lookup", input_schema={"type": "object"}),
        tool_id="tool-1",
        tool_version_id="version-1",
        function_name="mcp_lookup_bd4a77076205",
    )

    assert mcp_function_name(resolved) == "mcp_lookup_bd4a77076205"


def test_disabled_mcp_policy_wins_over_definition_drift() -> None:
    from app.entities.tools import Tool, ToolPolicy, ToolSource, ToolVersion
    from app.shareddomain.tools.catalog import McpCatalogLeaf, legacy_mcp_policy_mode

    leaf = McpCatalogLeaf(
        source=ToolSource(id="source-1", workspace_id="workspace-1", kind="mcp"),
        tool=Tool(
            id="tool-1",
            workspace_id="workspace-1",
            source_id="source-1",
            kind="mcp",
            stable_key="lookup",
        ),
        version=ToolVersion(
            id="version-2",
            workspace_id="workspace-1",
            tool_id="tool-1",
            definition_hash="new-hash",
        ),
        policy=ToolPolicy(
            workspace_id="workspace-1",
            tool_id="tool-1",
            tool_version_id="version-1",
            definition_hash="old-hash",
            approval="disabled",
        ),
    )

    assert legacy_mcp_policy_mode(leaf) == "disabled"


def test_mcp_hash_matches_legacy_annotation_normalization() -> None:
    from app.shareddomain.tools.catalog import mcp_definition_hash
    from app.shareddomain.tools.services import (
        _mcp_tool_definition,
        mcp_tool_definition_hash,
    )

    migration = load_migration()

    def assert_matches_legacy(definition: dict) -> None:
        legacy_definition = dict(definition)
        if "input_schema" not in legacy_definition:
            legacy_definition["input_schema"] = legacy_definition["inputSchema"]
        expected = mcp_tool_definition_hash(
            _mcp_tool_definition(legacy_definition)
        )
        assert mcp_definition_hash(definition) == expected
        assert migration._mcp_definition_hash(definition) == expected

    assert_matches_legacy(
        {
            "name": "alias-test",
            "description": None,
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {
                "readOnlyHint": None,
                "destructive_hint": False,
                "idempotentHint": True,
                "open_world_hint": None,
                "unknownHint": True,
            },
        }
    )
    assert_matches_legacy(
        {
            "name": "explicit-null",
            "input_schema": {"type": "object"},
            "annotations": None,
        }
    )

    generator = random.Random(20260817)
    annotation_fields = (
        ("read_only_hint", "readOnlyHint"),
        ("destructive_hint", "destructiveHint"),
        ("idempotent_hint", "idempotentHint"),
        ("open_world_hint", "openWorldHint"),
    )
    annotation_values = (None, True, False, 0, 1, "true", "false")
    for index in range(32):
        annotations = {}
        for snake_name, alias in annotation_fields:
            if generator.choice((True, False)):
                key = generator.choice((snake_name, alias))
                annotations[key] = generator.choice(annotation_values)
            if generator.randrange(8) == 0:
                annotations[snake_name] = True
                annotations[alias] = False
        if generator.choice((True, False)):
            annotations["title"] = generator.choice((None, "Audit hint"))
        schema_key = generator.choice(("input_schema", "inputSchema"))
        assert_matches_legacy(
            {
                "name": f"sample-{index}",
                "description": "Representative MCP Tool",
                schema_key: {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                },
                "annotations": annotations,
            }
        )


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


def test_migration_grants_tools_only_to_regular_members() -> None:
    migration = load_migration()
    common = {
        "bound_by_user_id": "agent-owner",
        "tool_owner_id": "server-owner",
        "grant_exists": False,
    }
    assert migration._should_backfill_use_grant(
        **common,
        workspace_role="member",
        is_global_admin=False,
    )
    assert not migration._should_backfill_use_grant(
        **common,
        workspace_role="admin",
        is_global_admin=False,
    )
    assert not migration._should_backfill_use_grant(
        **common,
        workspace_role="member",
        is_global_admin=True,
    )
    assert not migration._should_backfill_use_grant(
        **{**common, "bound_by_user_id": "server-owner"},
        workspace_role="member",
        is_global_admin=False,
    )


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
    mcp_source_fk = next(
        constraint
        for constraint in ToolSource.__table__.constraints
        if constraint.name == "fk_tool_sources_mcp_server_workspace"
    )
    assert isinstance(mcp_source_fk, ForeignKeyConstraint)
    assert mcp_source_fk.ondelete is None
    migration = load_migration()
    metadata = MetaData()
    original_op = migration.op
    migration.op = SimpleNamespace(
        create_table=lambda name, *items, **kwargs: Table(
            name, metadata, *items, **kwargs
        ),
        create_index=lambda *_args, **_kwargs: None,
        create_foreign_key=lambda *_args, **_kwargs: None,
    )
    try:
        migration_tables = migration._create_tables()
    finally:
        migration.op = original_op
    migration_source_fk = next(
        constraint
        for constraint in migration_tables["tool_sources"].constraints
        if constraint.name == "fk_tool_sources_mcp_server_workspace"
    )
    assert migration_source_fk.ondelete is None
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
    assert ("workspace_id", "kind", "name") in unique_columns(
        ToolSource.__table__
    )
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
    permission_membership_fk = next(
        constraint
        for constraint in ResourcePermission.__table__.constraints
        if constraint.name == "fk_resource_permission_workspace_user"
    )
    assert isinstance(permission_membership_fk, ForeignKeyConstraint)
    assert permission_membership_fk.ondelete == "CASCADE"

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


def test_private_catalog_filters_before_pagination_for_every_role() -> None:
    from fastapi import HTTPException

    from app.application.tools import (
        get_tool_catalog_detail,
        list_tool_catalog,
        require_tool_manage,
        require_tool_use,
    )
    from app.entities.resource_permission import ResourcePermission
    from app.infrastructure.repositories import resource_permission as permission_repository
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository

    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        owner_id, _ = create_active_user(client, admin_token, "tool-owner")
        grantee_id, _ = create_active_user(client, admin_token, "tool-grantee")
        stranger_id, _ = create_active_user(client, admin_token, "tool-stranger")
        workspace_admin_id, _ = create_active_user(
            client,
            admin_token,
            "tool-workspace-admin",
        )
        global_admin_id, _ = create_active_user(
            client,
            admin_token,
            "tool-global-admin",
        )
        for user_id in (owner_id, grantee_id, stranger_id, global_admin_id):
            add_workspace_member(client, admin_token, workspace_id, user_id)
        add_workspace_member(
            client,
            admin_token,
            workspace_id,
            workspace_admin_id,
            "admin",
        )

        owner_tool, owner_version = run(
            seed_private_tool(workspace_id, owner_id, "owner_private_tool")
        )
        workspace_admin_tool, _ = run(
            seed_private_tool(
                workspace_id,
                workspace_admin_id,
                "workspace_admin_private_tool",
            )
        )

        async def assert_catalog_scope() -> None:
            from app.entities.tools import ToolPolicy, ToolVersion

            async with get_session_factory()() as db:
                owner = await user_repository.get_user_by_id(db, owner_id)
                grantee = await user_repository.get_user_by_id(db, grantee_id)
                stranger = await user_repository.get_user_by_id(db, stranger_id)
                workspace_admin = await user_repository.get_user_by_id(
                    db,
                    workspace_admin_id,
                )
                global_admin = await user_repository.get_user_by_id(db, global_admin_id)
                assert all(
                    actor is not None
                    for actor in (owner, grantee, stranger, workspace_admin, global_admin)
                )
                assert global_admin is not None
                global_admin.is_global_admin = True
                await user_repository.save_user(db, global_admin)
                stale_policy = await tool_repository.save_tool_policy(
                    db,
                    ToolPolicy(
                        workspace_id=workspace_id,
                        tool_id=owner_tool.id,
                        tool_version_id=owner_version.id,
                        definition_hash=owner_version.definition_hash,
                        approval="auto",
                        effect="pure",
                    ),
                )
                current_version = await tool_repository.save_tool_version(
                    db,
                    ToolVersion(
                        workspace_id=workspace_id,
                        tool_id=owner_tool.id,
                        revision=2,
                        display_name="owner_private_tool_v2",
                        input_schema={"type": "object"},
                        execution_spec={"code": "result = {}"},
                        definition_hash="f" * 64,
                        created_by_user_id=owner_id,
                    ),
                )
                owner_tool.current_version_id = current_version.id
                await tool_repository.save_tool(db, owner_tool)
                await permission_repository.create_resource_permission(
                    db,
                    ResourcePermission(
                        workspace_id=workspace_id,
                        resource_type="tool",
                        resource_id=owner_tool.id,
                        user_id=grantee_id,
                        permission="view",
                        created_by_user_id=owner_id,
                    ),
                )
                await db.commit()

                async def visible_ids(actor, role: str, **pagination) -> list[str]:
                    rows = await list_tool_catalog(
                        db,
                        workspace_id,
                        actor,
                        role,
                        **pagination,
                    )
                    return [row.tool.id for row in rows]

                assert owner is not None
                assert grantee is not None
                assert stranger is not None
                assert workspace_admin is not None
                owner_ids = await visible_ids(owner, "member")
                grantee_ids = await visible_ids(grantee, "member")
                stranger_page = await visible_ids(stranger, "member", limit=1)
                workspace_admin_ids = await visible_ids(workspace_admin, "admin")
                global_admin_ids = await visible_ids(global_admin, "member")

                assert owner_tool.id in owner_ids
                assert owner_tool.id in grantee_ids
                assert owner_tool.id not in stranger_page
                assert owner_tool.id not in workspace_admin_ids
                assert owner_tool.id not in global_admin_ids
                assert workspace_admin_tool.id in workspace_admin_ids
                for ids in (
                    owner_ids,
                    grantee_ids,
                    stranger_page,
                    workspace_admin_ids,
                    global_admin_ids,
                ):
                    assert len(ids) >= 1
                builtin_id = stranger_page[0]
                assert builtin_id in owner_ids
                assert builtin_id in grantee_ids
                assert builtin_id in workspace_admin_ids
                assert builtin_id in global_admin_ids

                owner_detail = await get_tool_catalog_detail(
                    db,
                    workspace_id,
                    owner_tool.id,
                    owner,
                    "member",
                )
                assert owner_detail.permission == "owner"
                assert owner_detail.access.can_manage is True
                assert owner_detail.version is not None
                assert owner_detail.version.id == current_version.id
                assert owner_detail.policy is not None
                assert owner_detail.policy.id == stale_policy.id
                assert owner_detail.policy.tool_version_id == owner_version.id
                grantee_detail = await get_tool_catalog_detail(
                    db,
                    workspace_id,
                    owner_tool.id,
                    grantee,
                    "member",
                )
                assert grantee_detail.permission == "view"
                assert grantee_detail.access.can_view is True
                assert grantee_detail.access.can_use is False
                for check in (require_tool_use, require_tool_manage):
                    try:
                        check(grantee_detail.authorization)
                    except HTTPException as exc:
                        assert exc.status_code == 403
                    else:
                        raise AssertionError("A view grant must not imply use or manage.")

                for hidden_workspace_id, hidden_actor in (
                    (workspace_id, stranger),
                    ("wrong-workspace", owner),
                ):
                    try:
                        await get_tool_catalog_detail(
                            db,
                            hidden_workspace_id,
                            owner_tool.id,
                            hidden_actor,
                            "member",
                        )
                    except HTTPException as exc:
                        assert exc.status_code == 404
                    else:
                        raise AssertionError("Unseen Tools must be masked as not found.")

                for admin_actor, role in (
                    (workspace_admin, "admin"),
                    (global_admin, "member"),
                ):
                    admin_detail = await get_tool_catalog_detail(
                        db,
                        workspace_id,
                        owner_tool.id,
                        admin_actor,
                        role,
                    )
                    assert admin_detail.permission == "admin"
                    require_tool_manage(admin_detail.authorization)

                builtin_detail = await get_tool_catalog_detail(
                    db,
                    workspace_id,
                    builtin_id,
                    stranger,
                    "member",
                )
                assert builtin_detail.permission == "use"
                require_tool_use(builtin_detail.authorization)
                builtin_admin_detail = await get_tool_catalog_detail(
                    db,
                    workspace_id,
                    builtin_id,
                    workspace_admin,
                    "admin",
                )
                require_tool_manage(builtin_admin_detail.authorization)

        run(assert_catalog_scope())


def test_private_tool_permission_lifecycle_preserves_bindings() -> None:
    from fastapi import HTTPException

    from app.application.tools import (
        get_tool_catalog_detail,
        list_tool_permissions,
        require_tool_use,
        revoke_tool_permission,
        upsert_tool_permission,
    )
    from app.capabilities.llm.models import RegisteredModel
    from app.entities.agents import Agent
    from app.entities.tools import ApplicationToolBinding
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import audit as audit_repository
    from app.infrastructure.repositories import resource_permission as permission_repository
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository

    async def expect_status(expected_status: int, operation) -> None:
        try:
            await operation()
        except HTTPException as exc:
            assert exc.status_code == expected_status
        else:
            raise AssertionError(f"Expected HTTP {expected_status}.")

    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        owner_id, _ = create_active_user(client, admin_token, "grant-owner")
        grantee_id, _ = create_active_user(client, admin_token, "grant-grantee")
        stranger_id, _ = create_active_user(client, admin_token, "grant-stranger")
        workspace_admin_id, _ = create_active_user(
            client,
            admin_token,
            "grant-workspace-admin",
        )
        global_admin_id, _ = create_active_user(
            client,
            admin_token,
            "grant-global-admin",
        )
        inactive_id, _ = create_active_user(client, admin_token, "grant-inactive")
        nonmember_id, _ = create_active_user(client, admin_token, "grant-nonmember")
        cross_tenant_id, _ = create_active_user(
            client,
            admin_token,
            "grant-cross-tenant",
        )
        for user_id in (
            owner_id,
            grantee_id,
            stranger_id,
            global_admin_id,
            inactive_id,
        ):
            add_workspace_member(client, admin_token, workspace_id, user_id)
        add_workspace_member(
            client,
            admin_token,
            workspace_id,
            workspace_admin_id,
            "admin",
        )
        cross_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Cross Tenant Workspace",
                "admin_user_id": cross_tenant_id,
            },
        )
        assert cross_workspace.status_code == 201, cross_workspace.text
        tool, version = run(
            seed_private_tool(workspace_id, owner_id, "permission_lifecycle_tool")
        )

        async def assert_permission_lifecycle() -> None:
            async with get_session_factory()() as db:
                owner = await user_repository.get_user_by_id(db, owner_id)
                grantee = await user_repository.get_user_by_id(db, grantee_id)
                stranger = await user_repository.get_user_by_id(db, stranger_id)
                workspace_admin = await user_repository.get_user_by_id(
                    db,
                    workspace_admin_id,
                )
                global_admin = await user_repository.get_user_by_id(db, global_admin_id)
                inactive = await user_repository.get_user_by_id(db, inactive_id)
                assert all(
                    actor is not None
                    for actor in (
                        owner,
                        grantee,
                        stranger,
                        workspace_admin,
                        global_admin,
                        inactive,
                    )
                )
                assert global_admin is not None
                assert inactive is not None
                global_admin.is_global_admin = True
                inactive.is_active = False
                await user_repository.save_user(db, global_admin)
                await user_repository.save_user(db, inactive)
                await db.commit()
                assert owner is not None
                assert grantee is not None
                assert stranger is not None
                assert workspace_admin is not None

                first = await upsert_tool_permission(
                    db,
                    workspace_id,
                    tool.id,
                    grantee_id,
                    "view",
                    owner,
                    "member",
                )
                assert first.user.id == grantee_id
                assert first.grant.permission == "view"
                original_identity = (
                    first.grant.id,
                    first.grant.created_by_user_id,
                    first.grant.created_at.replace(tzinfo=None),
                )

                listed_by_owner = await list_tool_permissions(
                    db,
                    workspace_id,
                    tool.id,
                    owner,
                    "member",
                )
                listed_by_workspace_admin = await list_tool_permissions(
                    db,
                    workspace_id,
                    tool.id,
                    workspace_admin,
                    "admin",
                )
                listed_by_global_admin = await list_tool_permissions(
                    db,
                    workspace_id,
                    tool.id,
                    global_admin,
                    "member",
                )
                for entries in (
                    listed_by_owner,
                    listed_by_workspace_admin,
                    listed_by_global_admin,
                ):
                    assert [(entry.user.id, entry.grant.permission) for entry in entries] == [
                        (grantee_id, "view")
                    ]

                await expect_status(
                    403,
                    lambda: list_tool_permissions(
                        db,
                        workspace_id,
                        tool.id,
                        grantee,
                        "member",
                    ),
                )
                await expect_status(
                    404,
                    lambda: list_tool_permissions(
                        db,
                        workspace_id,
                        tool.id,
                        stranger,
                        "member",
                    ),
                )
                await expect_status(
                    403,
                    lambda: upsert_tool_permission(
                        db,
                        workspace_id,
                        tool.id,
                        stranger_id,
                        "view",
                        grantee,
                        "member",
                    ),
                )

                upgraded = await upsert_tool_permission(
                    db,
                    workspace_id,
                    tool.id,
                    grantee_id,
                    "use",
                    workspace_admin,
                    "admin",
                )
                repeated = await upsert_tool_permission(
                    db,
                    workspace_id,
                    tool.id,
                    grantee_id,
                    "use",
                    global_admin,
                    "member",
                )
                for entry in (upgraded, repeated):
                    identity = (
                        entry.grant.id,
                        entry.grant.created_by_user_id,
                        entry.grant.created_at.replace(tzinfo=None),
                    )
                    assert identity == original_identity, (
                        identity,
                        original_identity,
                    )
                    assert entry.grant.permission == "use"

                model = RegisteredModel(
                    workspace_id=workspace_id,
                    name="Grant Binding Model",
                    provider="grant_binding_provider",
                    provider_type="openai_compatible",
                    api_base="",
                    model_type="LLM",
                    model_name="grant-binding-model",
                    status="active",
                    created_by_user_id=owner_id,
                )
                db.add(model)
                await db.flush()
                application = await agent_repository.create_agent(
                    db,
                    Agent(
                        workspace_id=workspace_id,
                        name="Grant Binding Agent",
                        model_id=model.id,
                        created_by_user_id=owner_id,
                    ),
                )
                binding = await tool_repository.save_application_tool_binding(
                    db,
                    ApplicationToolBinding(
                        workspace_id=workspace_id,
                        application_id=application.id,
                        tool_id=tool.id,
                        tool_version_id=version.id,
                        bound_by_user_id=grantee_id,
                    ),
                )
                await db.commit()

                downgraded = await upsert_tool_permission(
                    db,
                    workspace_id,
                    tool.id,
                    grantee_id,
                    "view",
                    owner,
                    "member",
                )
                assert downgraded.grant.permission == "view"
                assert downgraded.grant.id == original_identity[0]
                retained = await tool_repository.get_application_tool_binding(
                    db,
                    workspace_id,
                    application.id,
                    tool.id,
                )
                assert retained is not None
                assert retained.id == binding.id
                view_detail = await get_tool_catalog_detail(
                    db,
                    workspace_id,
                    tool.id,
                    grantee,
                    "member",
                )
                try:
                    require_tool_use(view_detail.authorization)
                except HTTPException as exc:
                    assert exc.status_code == 403
                else:
                    raise AssertionError("A downgraded grant must not permit use.")

                await revoke_tool_permission(
                    db,
                    workspace_id,
                    tool.id,
                    grantee_id,
                    global_admin,
                    "member",
                )
                assert (
                    await permission_repository.get_user_grant(
                        db,
                        workspace_id,
                        "tool",
                        tool.id,
                        grantee_id,
                    )
                    is None
                )
                retained = await tool_repository.get_application_tool_binding(
                    db,
                    workspace_id,
                    application.id,
                    tool.id,
                )
                assert retained is not None
                assert retained.id == binding.id
                await expect_status(
                    404,
                    lambda: get_tool_catalog_detail(
                        db,
                        workspace_id,
                        tool.id,
                        grantee,
                        "member",
                    ),
                )

                for permission in ("edit", "manage"):
                    await expect_status(
                        422,
                        lambda permission=permission: upsert_tool_permission(
                            db,
                            workspace_id,
                            tool.id,
                            grantee_id,
                            permission,
                            owner,
                            "member",
                        ),
                    )
                await expect_status(
                    422,
                    lambda: upsert_tool_permission(
                        db,
                        workspace_id,
                        tool.id,
                        owner_id,
                        "view",
                        owner,
                        "member",
                    ),
                )
                await expect_status(
                    422,
                    lambda: upsert_tool_permission(
                        db,
                        workspace_id,
                        tool.id,
                        owner_id,
                        "view",
                        global_admin,
                        "member",
                    ),
                )
                for target_id in (inactive_id, nonmember_id, cross_tenant_id):
                    await expect_status(
                        404,
                        lambda target_id=target_id: upsert_tool_permission(
                            db,
                            workspace_id,
                            tool.id,
                            target_id,
                            "view",
                            owner,
                            "member",
                        ),
                    )

                logs = await audit_repository.list_workspace_audit_logs(
                    db,
                    workspace_id,
                    20,
                )
                tool_logs = [
                    log
                    for log in logs
                    if log.resource_type == "tool" and log.resource_id == tool.id
                ]
                assert {log.action for log in tool_logs} == {
                    "resource_permission.grant",
                    "resource_permission.revoke",
                }
                assert all(
                    log.details["user_id"] == grantee_id for log in tool_logs
                )

        run(assert_permission_lifecycle())


def test_mcp_resolution_requires_current_binding_owner_use_permission() -> None:
    from fastapi import HTTPException

    from app.capabilities.llm.models import RegisteredModel
    from app.entities.agents import Agent
    from app.entities.tools import ApplicationToolBinding, McpServer, ToolSource
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import mcp as mcp_repository
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository
    from app.shareddomain.tools.catalog import reconcile_mcp_discovery
    from app.shareddomain.tools.permissions import (
        revoke_tool_permission,
        upsert_tool_permission,
    )
    from app.shareddomain.tools.services import resolve_mcp_tools

    async def expect_status(expected_status: int, operation) -> None:
        try:
            await operation()
        except HTTPException as exc:
            assert exc.status_code == expected_status
        else:
            raise AssertionError(f"Expected HTTP {expected_status}.")

    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        owner_id, _ = create_active_user(client, admin_token, "mcp-use-owner")
        grantee_id, _ = create_active_user(client, admin_token, "mcp-use-grantee")
        add_workspace_member(client, admin_token, workspace_id, owner_id)
        add_workspace_member(client, admin_token, workspace_id, grantee_id)

        async def assert_resolution() -> None:
            async with get_session_factory()() as db:
                owner = await user_repository.get_user_by_id(db, owner_id)
                grantee = await user_repository.get_user_by_id(db, grantee_id)
                assert owner is not None and grantee is not None
                server = await mcp_repository.create_mcp_server(
                    db,
                    McpServer(
                        workspace_id=workspace_id,
                        name="Private Resolution MCP",
                        url="https://private-resolution.example.com/mcp",
                        created_by_user_id=owner.id,
                    ),
                )
                source = await tool_repository.save_tool_source(
                    db,
                    ToolSource(
                        workspace_id=workspace_id,
                        mcp_server_id=server.id,
                        kind="mcp",
                        name=server.name,
                        created_by_user_id=owner.id,
                    ),
                )
                await reconcile_mcp_discovery(
                    db,
                    server,
                    source,
                    [
                        {
                            "name": "lookup",
                            "description": "Lookup a record.",
                            "input_schema": {"type": "object"},
                            "annotations": {"readOnlyHint": True},
                        }
                    ],
                )
                tool = (await tool_repository.list_tools_by_source(
                    db,
                    workspace_id,
                    source.id,
                ))[0]
                assert tool.current_version_id is not None
                reference = [{"server_id": server.id, "tool_name": "lookup"}]
                await db.commit()

                await expect_status(
                    404,
                    lambda: resolve_mcp_tools(
                        db,
                        workspace_id,
                        reference,
                        strict=True,
                        actor=grantee,
                        workspace_role="member",
                    ),
                )
                await upsert_tool_permission(
                    db,
                    workspace_id,
                    tool.id,
                    grantee.id,
                    "view",
                    owner,
                    "member",
                )
                await expect_status(
                    403,
                    lambda: resolve_mcp_tools(
                        db,
                        workspace_id,
                        reference,
                        strict=True,
                        actor=grantee,
                        workspace_role="member",
                    ),
                )
                await upsert_tool_permission(
                    db,
                    workspace_id,
                    tool.id,
                    grantee.id,
                    "use",
                    owner,
                    "member",
                )
                resolved = await resolve_mcp_tools(
                    db,
                    workspace_id,
                    reference,
                    strict=True,
                    actor=grantee,
                    workspace_role="member",
                )
                assert [(item.tool_id, item.tool_version_id) for item in resolved] == [
                    (tool.id, tool.current_version_id)
                ]

                model = RegisteredModel(
                    workspace_id=workspace_id,
                    name="Private Resolution Model",
                    provider="private_resolution_provider",
                    provider_type="openai_compatible",
                    api_base="",
                    model_type="LLM",
                    model_name="private-resolution-model",
                    status="active",
                    created_by_user_id=owner.id,
                )
                db.add(model)
                await db.flush()
                application = await agent_repository.create_agent(
                    db,
                    Agent(
                        workspace_id=workspace_id,
                        name="Private Resolution Agent",
                        model_id=model.id,
                        created_by_user_id=owner.id,
                    ),
                )
                await tool_repository.save_application_tool_binding(
                    db,
                    ApplicationToolBinding(
                        workspace_id=workspace_id,
                        application_id=application.id,
                        tool_id=tool.id,
                        tool_version_id=tool.current_version_id,
                        bound_by_user_id=grantee.id,
                    ),
                )
                await db.commit()
                assert len(await resolve_mcp_tools(
                    db,
                    workspace_id,
                    reference,
                    strict=True,
                    application_id=application.id,
                )) == 1

                await revoke_tool_permission(
                    db,
                    workspace_id,
                    tool.id,
                    grantee.id,
                    owner,
                    "member",
                )
                assert await resolve_mcp_tools(
                    db,
                    workspace_id,
                    reference,
                    strict=False,
                    application_id=application.id,
                ) == []

        run(assert_resolution())


def test_mcp_resolution_rejects_missing_authorization_context() -> None:
    from app.shareddomain.tools.services import resolve_mcp_tools

    try:
        run(resolve_mcp_tools(
            SimpleNamespace(),
            "workspace-1",
            [{"server_id": "server-1", "tool_name": "lookup"}],
            strict=True,
        ))
    except ValueError as exc:
        assert str(exc) == "MCP Tool resolution requires an authorization context."
    else:
        raise AssertionError("MCP Tool resolution must fail closed without authorization.")


async def assert_mcp_server_deletion_preserves_tool_history(
    workspace_id: str,
) -> None:
    from app.capabilities.llm.models import RegisteredModel
    from app.entities.agents import Agent
    from app.entities.tools import (
        ApplicationToolBinding,
        McpServer,
        Tool,
        ToolInvocation,
        ToolPolicy,
        ToolSource,
        ToolVersion,
    )
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import mcp as mcp_repository
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository
    from app.shareddomain.tools import services as tool_services

    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        server = await mcp_repository.create_mcp_server(
            db,
            McpServer(
                workspace_id=workspace_id,
                name="History MCP",
                url="https://tools.example.com/mcp",
                tools=[],
                status="active",
                created_by_user_id=actor.id,
            ),
        )
        source = await tool_repository.save_tool_source(
            db,
            ToolSource(
                workspace_id=workspace_id,
                mcp_server_id=server.id,
                kind="mcp",
                name="History MCP",
                status="active",
                created_by_user_id=actor.id,
            ),
        )
        tool = await tool_repository.save_tool(
            db,
            Tool(
                workspace_id=workspace_id,
                source_id=source.id,
                kind="mcp",
                stable_key="echo",
                function_name="mcp_echo_history",
                status="active",
                availability="available",
                created_by_user_id=actor.id,
            ),
        )
        definition_hash = "a" * 64
        version = await tool_repository.save_tool_version(
            db,
            ToolVersion(
                workspace_id=workspace_id,
                tool_id=tool.id,
                revision=1,
                display_name="echo",
                input_schema={"type": "object"},
                execution_spec={"server_id": server.id, "tool_name": "echo"},
                definition_hash=definition_hash,
                created_by_user_id=actor.id,
            ),
        )
        tool.current_version_id = version.id
        await tool_repository.save_tool(db, tool)
        policy = await tool_repository.save_tool_policy(
            db,
            ToolPolicy(
                workspace_id=workspace_id,
                tool_id=tool.id,
                tool_version_id=version.id,
                definition_hash=definition_hash,
                approval="auto",
                effect="external_read",
                allowed_access_sources=["console"],
                reviewed_by_user_id=actor.id,
            ),
        )

        model = RegisteredModel(
            workspace_id=workspace_id,
            name="Tool History Model",
            provider="model_custom_provider",
            provider_type="openai_compatible",
            api_base="",
            model_type="LLM",
            model_name="history-model",
            status="active",
            created_by_user_id=actor.id,
        )
        db.add(model)
        await db.flush()
        application = await agent_repository.create_agent(
            db,
            Agent(
                workspace_id=workspace_id,
                name="Tool History Agent",
                instructions="Use the bound tool.",
                model_id=model.id,
                created_by_user_id=actor.id,
            ),
        )
        binding = await tool_repository.save_application_tool_binding(
            db,
            ApplicationToolBinding(
                workspace_id=workspace_id,
                application_id=application.id,
                tool_id=tool.id,
                tool_version_id=version.id,
                bound_by_user_id=actor.id,
            ),
        )
        invocation = await tool_repository.save_tool_invocation(
            db,
            ToolInvocation(
                workspace_id=workspace_id,
                origin="test",
                invocation_id="history-invocation",
                execution_user_id=actor.id,
                access_source="console",
                tool_id=tool.id,
                tool_version_id=version.id,
                policy_snapshot={"policy_id": policy.id},
                arguments={},
                arguments_hash="b" * 64,
                idempotency_key="history-invocation",
                status="succeeded",
                attempts=1,
                outcome="confirmed",
            ),
        )
        await db.commit()

        await tool_services.delete_mcp_server(db, server, actor)

        assert await mcp_repository.get_mcp_server_by_id(db, server.id) is None
        retained_source = await tool_repository.get_tool_source(
            db, workspace_id, source.id
        )
        retained_tool = await tool_repository.get_tool(db, workspace_id, tool.id)
        assert retained_source is not None
        assert retained_source.status == "archived"
        assert retained_source.mcp_server_id is None
        assert retained_source.name.startswith(f"archived-mcp-{source.id}-")
        assert retained_tool is not None
        assert retained_tool.status == "archived"
        assert retained_tool.availability == "unavailable"
        assert retained_tool.current_version_id == version.id
        retained_version = await tool_repository.get_tool_version(
            db, workspace_id, version.id
        )
        retained_policy = await tool_repository.get_tool_policy(
            db, workspace_id, tool.id
        )
        retained_binding = await tool_repository.get_application_tool_binding(
            db, workspace_id, application.id, tool.id
        )
        retained_invocation = await tool_repository.get_tool_invocation(
            db, workspace_id, invocation.id
        )
        assert retained_version is not None
        assert retained_version.definition_hash == definition_hash
        assert retained_policy is not None
        assert retained_policy.id == policy.id
        assert retained_policy.tool_version_id == version.id
        assert retained_binding is not None
        assert retained_binding.id == binding.id
        assert retained_binding.tool_version_id == version.id
        assert retained_invocation is not None
        assert retained_invocation.id == invocation.id
        assert retained_invocation.tool_version_id == version.id

        replacement = await mcp_repository.create_mcp_server(
            db,
            McpServer(
                workspace_id=workspace_id,
                name=server.name,
                url="https://replacement.example.com/mcp",
                created_by_user_id=actor.id,
            ),
        )
        replacement_source = await tool_repository.save_tool_source(
            db,
            ToolSource(
                workspace_id=workspace_id,
                mcp_server_id=replacement.id,
                kind="mcp",
                name=server.name,
                created_by_user_id=actor.id,
            ),
        )
        await db.commit()
        assert replacement_source.id != source.id


async def assert_mcp_discovery_materializes_first_leaf(
    workspace_id: str,
) -> None:
    from app.entities.tools import McpServer, Tool, ToolSource
    from app.infrastructure.repositories import mcp as mcp_repository
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository
    from app.shareddomain.tools.catalog import (
        mcp_function_name_candidates,
        reconcile_mcp_discovery,
    )

    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        server = await mcp_repository.create_mcp_server(
            db,
            McpServer(
                workspace_id=workspace_id,
                name="Catalog MCP",
                url="https://catalog.example.com/mcp",
                tools=[],
                created_by_user_id=actor.id,
            ),
        )
        source = await tool_repository.save_tool_source(
            db,
            ToolSource(
                workspace_id=workspace_id,
                mcp_server_id=server.id,
                kind="mcp",
                name=server.name,
                created_by_user_id=actor.id,
            ),
        )
        discovery = [
            {
                "name": "lookup",
                "description": "Lookup a record.",
                "input_schema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                },
            }
        ]

        candidates = mcp_function_name_candidates(server.id, "lookup")
        sources = await tool_repository.list_tool_sources(db, workspace_id)
        python_source = next(item for item in sources if item.kind == "python")
        await tool_repository.save_tool(
            db,
            Tool(
                workspace_id=workspace_id,
                source_id=python_source.id,
                kind="python",
                stable_key="mcp_collision_blocker",
                function_name=candidates[0],
                created_by_user_id=actor.id,
            ),
        )

        await reconcile_mcp_discovery(db, server, source, discovery)
        tools = await tool_repository.list_tools_by_source(
            db,
            workspace_id,
            source.id,
        )
        assert len(tools) == 1
        tool = tools[0]
        assert tool.stable_key == "lookup"
        assert tool.function_name == candidates[1]
        assert tool.created_by_user_id == actor.id
        assert tool.availability == "available"
        assert tool.current_version_id is not None
        version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            tool.current_version_id,
        )
        assert version is not None
        assert version.revision == 1
        assert version.execution_spec == {
            "server_id": server.id,
            "tool_name": "lookup",
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
            },
        }
        policy = await tool_repository.get_tool_policy(db, workspace_id, tool.id)
        assert policy is not None
        assert policy.tool_version_id == version.id
        assert policy.definition_hash == version.definition_hash
        assert policy.approval == "each_call"
        assert policy.effect == "unknown"
        assert policy.allowed_access_sources == ["console"]
        assert policy.workflow_callable is False
        assert policy.parallel_safe is False

        original_tool_id = tool.id
        original_version_id = version.id
        original_policy_hash = policy.definition_hash
        await reconcile_mcp_discovery(db, server, source, discovery)
        versions = await tool_repository.list_tool_versions(
            db,
            workspace_id,
            tool.id,
        )
        assert [item.id for item in versions] == [original_version_id]

        changed = [
            {
                **discovery[0],
                "description": "Lookup a changed record.",
            }
        ]
        await reconcile_mcp_discovery(db, server, source, changed)
        tool = (await tool_repository.list_tools_by_source(
            db,
            workspace_id,
            source.id,
        ))[0]
        versions = await tool_repository.list_tool_versions(
            db,
            workspace_id,
            tool.id,
        )
        assert tool.id == original_tool_id
        assert len(versions) == 2
        assert versions[0].revision == 2
        assert tool.current_version_id == versions[0].id
        policy = await tool_repository.get_tool_policy(db, workspace_id, tool.id)
        assert policy is not None
        assert policy.definition_hash == original_policy_hash
        assert policy.tool_version_id == original_version_id

        await reconcile_mcp_discovery(db, server, source, [])
        tool = (await tool_repository.list_tools_by_source(
            db,
            workspace_id,
            source.id,
        ))[0]
        assert tool.availability == "unavailable"

        await reconcile_mcp_discovery(db, server, source, discovery)
        tool = (await tool_repository.list_tools_by_source(
            db,
            workspace_id,
            source.id,
        ))[0]
        versions = await tool_repository.list_tool_versions(
            db,
            workspace_id,
            tool.id,
        )
        assert tool.id == original_tool_id
        assert tool.current_version_id == original_version_id
        assert tool.availability == "available"
        assert len(versions) == 2
        await db.rollback()


async def assert_tool_policy_revision_compare_and_swap(workspace_id: str) -> None:
    from app.infrastructure.repositories import tools as tool_repository

    async with get_session_factory()() as first_db, get_session_factory()() as second_db:
        tools = await tool_repository.list_tools(first_db, workspace_id)
        builtin = next(tool for tool in tools if tool.stable_key == "current_time")
        first = await tool_repository.get_tool_policy(
            first_db,
            workspace_id,
            builtin.id,
        )
        second = await tool_repository.get_tool_policy(
            second_db,
            workspace_id,
            builtin.id,
        )
        assert first is not None and second is not None
        assert first.revision == second.revision

        expected_revision = first.revision
        first.revision += 1
        first.effect = "external_read"
        assert (
            await tool_repository.update_tool_policy_if_revision(
                first_db,
                first,
                expected_revision,
            )
            is not None
        )
        await first_db.commit()

        second.revision += 1
        second.effect = "external_write"
        assert (
            await tool_repository.update_tool_policy_if_revision(
                second_db,
                second,
                expected_revision,
            )
            is None
        )
        await second_db.rollback()


def test_workspace_creation_initializes_system_catalog() -> None:
    with test_client() as client:
        _token, workspace_id = activate_admin(client)
        run(assert_workspace_system_catalog(workspace_id))
        run(assert_tool_policy_revision_compare_and_swap(workspace_id))
        run(assert_mcp_discovery_materializes_first_leaf(workspace_id))
        run(assert_mcp_server_deletion_preserves_tool_history(workspace_id))


def main() -> None:
    test_stable_catalog_contract_matches_legacy_mcp_identity()
    test_mcp_network_policy_migration_is_reversible_and_defaults_legacy()
    test_legacy_disabled_tools_remain_disabled_after_backfill()
    test_mcp_function_name_candidates_extend_stable_digest_on_collision()
    test_resolved_mcp_tool_preserves_catalog_function_name()
    test_disabled_mcp_policy_wins_over_definition_drift()
    test_mcp_hash_matches_legacy_annotation_normalization()
    test_migration_collects_policy_only_tools_deterministically()
    test_migration_grants_tools_only_to_regular_members()
    test_entities_and_orm_columns_match_exactly()
    test_orm_enforces_tenant_scoped_relations_and_legal_states()
    test_tool_versions_are_immutable_at_repository_boundary()
    test_migration_reference_scanner_keeps_historical_mcp_tuples()
    test_private_catalog_filters_before_pagination_for_every_role()
    test_private_tool_permission_lifecycle_preserves_bindings()
    test_mcp_resolution_requires_current_binding_owner_use_permission()
    test_mcp_resolution_rejects_missing_authorization_context()
    test_workspace_creation_initializes_system_catalog()
    print("TOOLS_SUITE_OK")


if __name__ == "__main__":
    main()
