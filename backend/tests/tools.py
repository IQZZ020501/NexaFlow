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
    settings as test_settings,
    test_client,
)

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    MetaData,
    Table,
    UniqueConstraint,
    event,
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


def test_agent_publication_migration_supports_sqlite_foreign_keys() -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    migration = load_agent_publication_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("CREATE TABLE workspaces (id TEXT PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE users (id TEXT PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE agents ("
                "id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, "
                "UNIQUE (workspace_id, id), "
                "FOREIGN KEY (workspace_id) REFERENCES workspaces(id))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE agent_runs ("
                "id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, "
                "agent_id TEXT NOT NULL, "
                "FOREIGN KEY (workspace_id, agent_id) "
                "REFERENCES agents(workspace_id, id))"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration._assert_agent_runs_drained = lambda _bind: None
        migration._backfill = lambda _bind, _versions: None
        migration.upgrade()

        inspector = inspect(connection)
        assert "agent_publication_versions" in inspector.get_table_names()
        assert {
            "ck_agent_runs_configuration_source",
            "ck_agent_runs_snapshot_schema_version",
            "ck_agent_runs_publication_source",
        }.issubset(
            {
                constraint["name"]
                for constraint in inspector.get_check_constraints("agent_runs")
            }
        )
        assert any(
            foreign_key["name"] == "fk_agent_runs_publication_workspace"
            for foreign_key in inspector.get_foreign_keys("agent_runs")
        )
        assert not any(
            foreign_key["referred_table"] == "agent_publication_versions"
            for foreign_key in inspector.get_foreign_keys("agents")
        )

        migration._assert_downgrade_safe = lambda _bind: None
        migration._restore_migration_grants = lambda _bind: None
        migration._restore_legacy_agent_published_snapshots = lambda _bind: None
        migration._remove_migrated_agent_tool_invocations = lambda _bind: None
        migration.downgrade()
        inspector = inspect(connection)
        assert "agent_publication_versions" not in inspector.get_table_names()
        assert "configuration_source" not in {
            column["name"] for column in inspector.get_columns("agent_runs")
        }


def load_agent_publication_migration():
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/202608160005_agent_publication_versions.py"
    )
    spec = spec_from_file_location("agent_publication_versions", path)
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

    migration = load_migration()
    candidates = mcp_function_name_candidates("server-1", "order items!")
    assert candidates[:3] == (
        "mcp_order_items_bd4a7707",
        "mcp_order_items_bd4a77076205",
        "mcp_order_items_bd4a770762057d62",
    )
    assert all(len(candidate) <= 64 for candidate in candidates)
    assert len(candidates[-1]) == 64
    assert migration._mcp_function_name_candidates(
        "server-1", "order items!"
    ) == candidates


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
    overlong = ResolvedMcpTool(
        server=resolved.server,
        definition=resolved.definition,
        tool_id=resolved.tool_id,
        tool_version_id=resolved.tool_version_id,
        function_name="mcp_" + "x" * 80,
    )
    overlong_name = mcp_function_name(overlong)
    assert len(overlong_name) == 64
    assert overlong_name == mcp_function_name(overlong)
    assert overlong_name != mcp_function_name(
        ResolvedMcpTool(server=resolved.server, definition=resolved.definition)
    )


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


def test_agent_publication_backfill_does_not_restore_membership_revoked_use() -> None:
    migration = load_agent_publication_migration()
    metadata = MetaData()
    users = Table(
        "users",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("is_global_admin", sa.Boolean, nullable=False),
    )
    memberships = Table(
        "workspace_memberships",
        metadata,
        sa.Column("workspace_id", sa.String, primary_key=True),
        sa.Column("user_id", sa.String, primary_key=True),
        sa.Column("role", sa.String, nullable=False),
    )
    permissions = Table(
        "resource_permissions",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, nullable=False),
        sa.Column("resource_type", sa.String, nullable=False),
        sa.Column("resource_id", sa.String, nullable=False),
        sa.Column("user_id", sa.String, nullable=False),
        sa.Column("permission", sa.String, nullable=False),
        sa.Column("created_by_user_id", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    audit_logs = Table(
        "audit_logs",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("resource_type", sa.String, nullable=False),
        sa.Column("resource_id", sa.String, nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    published_at = datetime(2026, 8, 15, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            users.insert(),
            {"id": "binder", "is_active": True, "is_global_admin": False},
        )
        connection.execute(
            memberships.insert(),
            {"workspace_id": "workspace", "user_id": "binder", "role": "member"},
        )
        connection.execute(
            audit_logs.insert(),
            {
                "id": "member-removed",
                "workspace_id": "workspace",
                "action": "workspace.member.remove",
                "resource_type": "workspace_member",
                "resource_id": "binder",
                "details": {"role": "member"},
                "created_at": published_at,
            },
        )
        markers = migration._backfill_snapshot_use_grants(
            connection,
            {
                ("workspace", "tool", "binder"): {
                    "created_at": published_at,
                    "agent_ids": {"agent"},
                }
            },
            {("workspace", "tool"): "tool-owner"},
        )
        assert markers == {}
        assert connection.execute(sa.select(permissions.c.id)).all() == []

        # A new explicit grant after rejoining remains authoritative.
        connection.execute(
            permissions.insert(),
            {
                "id": "explicit-use",
                "workspace_id": "workspace",
                "resource_type": "tool",
                "resource_id": "tool",
                "user_id": "binder",
                "permission": "use",
                "created_by_user_id": "admin",
                "created_at": published_at,
                "updated_at": published_at,
            },
        )
        assert migration._backfill_snapshot_use_grants(
            connection,
            {
                ("workspace", "tool", "binder"): {
                    "created_at": published_at,
                    "agent_ids": {"agent"},
                }
            },
            {("workspace", "tool"): "tool-owner"},
        ) == {}
        assert connection.execute(sa.select(permissions.c.id)).all() == [
            ("explicit-use",)
        ]


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
        assert {tool.stable_key for tool in tools} == {
            "current_time",
            "inline_python",
            "python_artifact",
        }
        tool = next(tool for tool in tools if tool.stable_key == "current_time")
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

        artifact_tool = next(
            item for item in tools if item.stable_key == "python_artifact"
        )
        artifact_version = await repository.get_tool_version(
            db,
            workspace_id,
            artifact_tool.current_version_id or "",
        )
        assert artifact_version is not None
        assert artifact_version.execution_spec == {"builtin": "python_artifact"}
        assert set(artifact_version.input_schema["properties"]["format"]["enum"]) == {
            "docx",
            "html",
        }


def test_generated_artifact_link_serves_static_html() -> None:
    from app.application.artifacts import create_generated_artifact
    from app.infrastructure.session import get_session_factory

    with test_client() as client:
        _admin_token, workspace_id = activate_admin(client)

        async def create():
            async with get_session_factory()() as db:
                first = await create_generated_artifact(
                    db,
                    test_settings(),
                    workspace_id=workspace_id,
                    run_id="run-1",
                    idempotency_key="artifact-idempotency-key",
                    artifact_format="html",
                    filename="page.html",
                    content=b"<html><style>body{color:#123}</style><body>ready</body></html>",
                )
                second = await create_generated_artifact(
                    db,
                    test_settings(),
                    workspace_id=workspace_id,
                    run_id="run-1",
                    idempotency_key="artifact-idempotency-key",
                    artifact_format="html",
                    filename="page.html",
                    content=b"ignored retry",
                )
                await db.commit()
                return first, second

        first, second = asyncio.run(create())
        assert first.artifact_id == second.artifact_id
        assert first.download_url == second.download_url
        response = client.get(first.download_url)
        assert response.status_code == 200, response.text
        assert response.content.endswith(b"</html>")
        assert response.headers["content-type"].startswith("text/html")
        assert "sandbox" in response.headers["content-security-policy"]
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"


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
        list_mcp_catalog_leaves,
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

        query_count = 0

        def count_query(*_args) -> None:
            nonlocal query_count
            query_count += 1

        assert db.bind is not None
        event.listen(db.bind.sync_engine, "before_cursor_execute", count_query)
        try:
            leaves = await list_mcp_catalog_leaves(db, workspace_id, server.id)
        finally:
            event.remove(db.bind.sync_engine, "before_cursor_execute", count_query)
        assert len(leaves) == 1
        assert leaves[0].tool.id == tool.id
        assert leaves[0].version.id == version.id
        assert leaves[0].policy is not None
        assert query_count == 1

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


async def assert_tool_runtime_is_durable(workspace_id: str) -> None:
    from datetime import timedelta

    from app.application.tool_runtime import (
        execute_tool_invocation,
        list_recoverable_tool_test_invocation_ids,
        queue_tool_invocation,
    )
    from app.infrastructure.config import Settings
    from app.infrastructure.model_utils import utc_now
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository
    from app.ports.tool_runtime import (
        ToolAdapterBusy,
        ToolInvocationContext,
        ToolRuntimeResult,
    )
    from app.shareddomain.tools.runtime import build_tool_snapshot

    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        tool = next(
            item
            for item in await tool_repository.list_tools(db, workspace_id)
            if item.stable_key == "current_time"
        )
        source = await tool_repository.get_tool_source(db, workspace_id, tool.source_id)
        version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            tool.current_version_id or "",
        )
        policy = await tool_repository.get_tool_policy(db, workspace_id, tool.id)
        assert source is not None and version is not None and policy is not None
        snapshot = build_tool_snapshot(tool, source, version, policy, actor.id)
        context = ToolInvocationContext(
            workspace_id=workspace_id,
            origin="test",
            root_run_id=None,
            run_id=None,
            invocation_id="durable-runtime",
            execution_user_id=actor.id,
            access_source="console",
            deadline_at=utc_now() + timedelta(seconds=30),
            idempotency_key=f"durable-runtime:{workspace_id}",
        )
        rolled_back_context = ToolInvocationContext(
            **{
                **context.__dict__,
                "invocation_id": "rolled-back-runtime",
                "idempotency_key": f"rolled-back-runtime:{workspace_id}",
            }
        )
        rolled_back = await queue_tool_invocation(
            db,
            snapshot,
            {},
            rolled_back_context,
        )
        await db.rollback()

    async with get_session_factory()() as db:
        assert await tool_repository.get_tool_invocation(
            db,
            workspace_id,
            rolled_back.id,
        ) is None
        invocation = await queue_tool_invocation(db, snapshot, {}, context)
        await db.commit()
    async with get_session_factory()() as db:
        invocation = await queue_tool_invocation(db, snapshot, {}, context)
        duplicate = await queue_tool_invocation(db, snapshot, {}, context)
        assert duplicate.id == invocation.id
        await db.commit()

    class FakeAdapter:
        kind = "builtin"

        def __init__(self, data: dict[str, str]) -> None:
            self.data = data
            self.calls = 0

        async def invoke(self, snapshot, arguments, context):
            self.calls += 1
            return ToolRuntimeResult(
                ok=True,
                data=self.data,
                summary="Done.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )

    adapter = FakeAdapter({"iso8601": "2026-08-17T00:00:00+00:00"})
    settings = Settings.from_env(require_bootstrap=False)
    first = await execute_tool_invocation(
        invocation.id,
        settings,
        worker_task_id="runtime-worker-1",
        adapter=adapter,
    )
    assert first.ok is True
    assert adapter.calls == 1

    async with get_session_factory()() as db:
        tool = await tool_repository.get_tool(db, workspace_id, snapshot.tool_id)
        assert tool is not None
        tool.status = "disabled"
        await tool_repository.save_tool(db, tool)
        await db.commit()

    replay = await execute_tool_invocation(
        invocation.id,
        settings,
        worker_task_id="runtime-worker-2",
        adapter=adapter,
    )
    assert replay.ok is True
    assert adapter.calls == 1

    disabled_context = ToolInvocationContext(
        **{
            **context.__dict__,
            "invocation_id": "disabled-runtime",
            "idempotency_key": f"disabled-runtime:{workspace_id}",
        }
    )
    async with get_session_factory()() as db:
        disabled_invocation = await queue_tool_invocation(
            db,
            snapshot,
            {},
            disabled_context,
        )
        await db.commit()
    disabled = await execute_tool_invocation(
        disabled_invocation.id,
        settings,
        worker_task_id="runtime-worker-3",
        adapter=adapter,
    )
    assert disabled.ok is False
    assert disabled.error_code == "tool_disabled"
    assert adapter.calls == 1

    async with get_session_factory()() as db:
        tool = await tool_repository.get_tool(db, workspace_id, snapshot.tool_id)
        assert tool is not None
        tool.status = "active"
        await tool_repository.save_tool(db, tool)
        await db.commit()
        invalid_context = ToolInvocationContext(
            **{
                **context.__dict__,
                "invocation_id": "invalid-output-runtime",
                "idempotency_key": f"invalid-output-runtime:{workspace_id}",
            }
        )
        invalid_invocation = await queue_tool_invocation(
            db,
            snapshot,
            {},
            invalid_context,
        )
        await db.commit()
    invalid_adapter = FakeAdapter({})
    invalid = await execute_tool_invocation(
        invalid_invocation.id,
        settings,
        worker_task_id="runtime-worker-4",
        adapter=invalid_adapter,
    )
    assert invalid.ok is False
    assert invalid.error_code == "invalid_tool_output"

    async with get_session_factory()() as db:
        concurrent_context = ToolInvocationContext(
            **{
                **context.__dict__,
                "invocation_id": "concurrent-runtime",
                "idempotency_key": f"concurrent-runtime:{workspace_id}",
            }
        )
        concurrent_invocation = await queue_tool_invocation(
            db,
            snapshot,
            {},
            concurrent_context,
        )
        await db.commit()

    class BlockingAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__({"iso8601": "2026-08-17T00:00:00+00:00"})
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def invoke(self, snapshot, arguments, context):
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return ToolRuntimeResult(
                ok=True,
                data=self.data,
                summary="Done.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )

    blocking = BlockingAdapter()
    first_worker = asyncio.create_task(
        execute_tool_invocation(
            concurrent_invocation.id,
            settings,
            worker_task_id="concurrent-worker-1",
            adapter=blocking,
        )
    )
    await blocking.started.wait()
    try:
        await execute_tool_invocation(
            concurrent_invocation.id,
            settings,
            worker_task_id="concurrent-worker-2",
            adapter=blocking,
        )
    except Exception as exc:
        from app.application.tool_runtime import ToolInvocationBusy

        assert isinstance(exc, ToolInvocationBusy)
    else:
        raise AssertionError("A second worker must not execute a claimed invocation.")
    blocking.release.set()
    assert (await first_worker).ok is True
    assert blocking.calls == 1

    async with get_session_factory()() as db:
        busy_context = ToolInvocationContext(
            **{
                **context.__dict__,
                "invocation_id": "busy-runtime",
                "idempotency_key": f"busy-runtime:{workspace_id}",
            }
        )
        busy_invocation = await queue_tool_invocation(db, snapshot, {}, busy_context)
        await db.commit()

    class BusyAdapter:
        kind = "builtin"

        async def invoke(self, snapshot, arguments, context):
            raise ToolAdapterBusy("busy")

    for attempt in range(2):
        try:
            await execute_tool_invocation(
                busy_invocation.id,
                settings,
                worker_task_id=f"busy-worker-{attempt}",
                adapter=BusyAdapter(),
            )
        except Exception as exc:
            from app.application.tool_runtime import ToolInvocationBusy

            assert isinstance(exc, ToolInvocationBusy)
        else:
            raise AssertionError("A busy provider must requeue before the last attempt.")
    exhausted = await execute_tool_invocation(
        busy_invocation.id,
        settings,
        worker_task_id="busy-worker-2",
        adapter=BusyAdapter(),
    )
    assert exhausted.ok is False
    assert exhausted.error_code == "tool_attempts_exhausted"
    async with get_session_factory()() as db:
        # RUN-008: a pure tool whose worker crashed BEFORE provider dispatch
        # (lease expired, attempts below max) is safely retried after the
        # lease expires — the provider is invoked again.
        crashed_context = ToolInvocationContext(
            **{
                **context.__dict__,
                "invocation_id": "crashed-pure-runtime",
                "idempotency_key": f"crashed-pure-runtime:{workspace_id}",
            }
        )
        crashed_pure = await queue_tool_invocation(db, snapshot, {}, crashed_context)
        crashed_pure.status = "running"
        crashed_pure.worker_task_id = "crashed-pure-worker"
        crashed_pure.lease_expires_at = utc_now() - timedelta(seconds=1)
        crashed_pure.started_at = crashed_pure.lease_expires_at
        await tool_repository.save_tool_invocation(db, crashed_pure)
        await db.commit()
    calls_before_retry = adapter.calls
    retried = await execute_tool_invocation(
        crashed_pure.id,
        settings,
        worker_task_id="pure-recovery-worker",
        adapter=adapter,
    )
    assert retried.ok is True
    assert adapter.calls == calls_before_retry + 1

    async with get_session_factory()() as db:
        stored_busy = await tool_repository.get_tool_invocation(
            db,
            workspace_id,
            busy_invocation.id,
        )
        assert stored_busy is not None
        assert stored_busy.status == "failed"
        assert stored_busy.attempts == stored_busy.max_attempts == 3

        drift_context = ToolInvocationContext(
            **{
                **context.__dict__,
                "invocation_id": "policy-drift-runtime",
                "idempotency_key": f"policy-drift-runtime:{workspace_id}",
            }
        )
        drift_invocation = await queue_tool_invocation(db, snapshot, {}, drift_context)
        await db.commit()
        policy = await tool_repository.get_tool_policy(db, workspace_id, snapshot.tool_id)
        assert policy is not None
        expected_revision = policy.revision
        policy.revision += 1
        policy.updated_at = utc_now()
        assert await tool_repository.update_tool_policy_if_revision(
            db,
            policy,
            expected_revision,
        ) is not None
        await db.commit()
    drifted = await execute_tool_invocation(
        drift_invocation.id,
        settings,
        worker_task_id="drift-worker",
        adapter=adapter,
    )
    assert drifted.ok is False
    assert drifted.error_code == "tool_policy_changed"

    async with get_session_factory()() as db:
        tool = await tool_repository.get_tool(db, workspace_id, snapshot.tool_id)
        source = await tool_repository.get_tool_source(
            db,
            workspace_id,
            snapshot.source_id,
        )
        version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            snapshot.version_id,
        )
        policy = await tool_repository.get_tool_policy(db, workspace_id, snapshot.tool_id)
        assert tool is not None and source is not None and version is not None
        assert policy is not None
        expected_revision = policy.revision
        policy.revision += 1
        policy.effect = "external_write"
        policy.updated_at = utc_now()
        assert await tool_repository.update_tool_policy_if_revision(
            db,
            policy,
            expected_revision,
        ) is not None
        write_snapshot = build_tool_snapshot(tool, source, version, policy, actor.id)
        write_context = ToolInvocationContext(
            **{
                **context.__dict__,
                "invocation_id": "expired-write-runtime",
                "idempotency_key": f"expired-write-runtime:{workspace_id}",
            }
        )
        write_invocation = await queue_tool_invocation(
            db,
            write_snapshot,
            {},
            write_context,
        )
        write_invocation.status = "running"
        write_invocation.attempts = write_invocation.max_attempts
        write_invocation.worker_task_id = "crashed-write-worker"
        write_invocation.lease_expires_at = utc_now() - timedelta(seconds=1)
        write_invocation.started_at = write_invocation.lease_expires_at
        await tool_repository.save_tool_invocation(db, write_invocation)
        await db.commit()
    assert write_invocation.id in await list_recoverable_tool_test_invocation_ids()
    calls_before_recovery = adapter.calls
    recovered_write = await execute_tool_invocation(
        write_invocation.id,
        settings,
        worker_task_id="write-recovery-worker",
        adapter=adapter,
    )
    assert recovered_write.ok is False
    assert recovered_write.outcome == "uncertain"
    assert recovered_write.error_code == "tool_outcome_uncertain"
    assert adapter.calls == calls_before_recovery


async def assert_python_tool_lifecycle(workspace_id: str) -> None:
    from datetime import timedelta

    from app.application.tool_runtime import execute_tool_invocation, queue_tool_invocation
    from app.infrastructure.config import Settings
    from app.infrastructure.model_utils import utc_now
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository
    from app.ports.tool_runtime import ToolInvocationContext, ToolRuntimeResult
    from app.shareddomain.tools.python_tools import (
        build_python_test_snapshot,
        create_python_tool,
        publish_python_tool,
        update_python_tool_draft,
    )

    input_schema = {
        "type": "object",
        "properties": {"value": {"type": "string", "maxLength": 64}},
        "required": ["value"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {"value": {"type": "string", "maxLength": 64}},
        "required": ["value"],
        "additionalProperties": False,
    }
    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        tool, draft = await create_python_tool(
            db,
            workspace_id,
            actor,
            "admin",
            display_name="Uppercase value",
            description="Uppercase one value.",
            input_schema=input_schema,
            output_schema=output_schema,
            code="result = {'value': inputs['value'].upper()}",
        )
        assert tool.current_version_id is None
        assert draft.revision == 1
        draft = await update_python_tool_draft(
            db,
            workspace_id,
            tool.id,
            actor,
            "admin",
            expected_revision=1,
            display_name="Uppercase value",
            description="Uppercase one value safely.",
            input_schema=input_schema,
            output_schema=output_schema,
            code="result = {'value': inputs['value'].upper()}",
        )
        assert draft.revision == 2
        snapshot = await build_python_test_snapshot(
            db,
            workspace_id,
            tool.id,
            actor,
            "admin",
        )
        stored_tool = await tool_repository.get_tool(db, workspace_id, tool.id)
        assert stored_tool is not None and stored_tool.current_version_id is None
        context = ToolInvocationContext(
            workspace_id=workspace_id,
            origin="test",
            root_run_id=None,
            run_id=None,
            invocation_id=f"python-test:{tool.id}",
            execution_user_id=actor.id,
            access_source="console",
            deadline_at=utc_now() + timedelta(seconds=30),
            idempotency_key=f"python-test:{tool.id}",
        )
        invocation = await queue_tool_invocation(
            db,
            snapshot,
            {"value": "nexa"},
            context,
        )
        await db.commit()

    class PythonFakeAdapter:
        kind = "python"

        async def invoke(self, snapshot, arguments, context):
            return ToolRuntimeResult(
                ok=True,
                data={"value": arguments["value"].upper()},
                summary="Done.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )

    result = await execute_tool_invocation(
        invocation.id,
        Settings.from_env(require_bootstrap=False),
        worker_task_id="python-test-worker",
        adapter=PythonFakeAdapter(),
    )
    assert result.ok is True
    assert result.data == {"value": "NEXA"}

    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        published_tool, version, policy = await publish_python_tool(
            db,
            workspace_id,
            tool.id,
            actor,
            "admin",
        )
        assert published_tool.current_version_id == snapshot.version_id == version.id
        assert policy.tool_version_id == version.id
        assert policy.approval == "auto"
        assert policy.effect == "pure"
        assert policy.parallel_safe is False



async def assert_tool_runtime_edge_branches(
    workspace_id: str,
    stranger_id: str,
) -> None:
    import dataclasses
    from datetime import timedelta
    from unittest.mock import patch

    from app.application.tool_runtime import (
        ToolInvocationBusy,
        ToolInvocationConflict,
        execute_tool_invocation,
        preflight_tool_snapshot,
        queue_tool_invocation,
    )
    from app.entities.tools import McpServer, Tool, ToolPolicy, ToolSource, ToolVersion
    from app.infrastructure.config import Settings
    from app.infrastructure.model_utils import utc_now
    from app.infrastructure.repositories import mcp as mcp_repository
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository
    from app.ports.tool_runtime import ToolInvocationContext, ToolRuntimeResult
    from app.shareddomain.tools.models import ToolInvocation as ToolInvocationOrm
    from app.shareddomain.tools.runtime import (
        TOOL_APPROVAL_EACH_CALL,
        build_tool_snapshot,
        tool_snapshot_payload,
    )

    settings = Settings.from_env(require_bootstrap=False)

    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        tool = next(
            item
            for item in await tool_repository.list_tools(db, workspace_id)
            if item.stable_key == "current_time"
        )
        source = await tool_repository.get_tool_source(db, workspace_id, tool.source_id)
        version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            tool.current_version_id or "",
        )
        policy = await tool_repository.get_tool_policy(db, workspace_id, tool.id)
        assert source is not None and version is not None and policy is not None
        expected = policy.revision
        policy.revision += 1
        policy.approval = "auto"
        policy.effect = "pure"
        policy.allowed_access_sources = ["console", "public", "api"]
        policy.workflow_callable = True
        policy.parallel_safe = True
        policy.updated_at = utc_now()
        assert (
            await tool_repository.update_tool_policy_if_revision(
                db,
                policy,
                expected,
            )
            is not None
        )
        snapshot = build_tool_snapshot(tool, source, version, policy, actor.id)
        tool_id = tool.id
        source_id = source.id
        actor_id = actor.id
        await db.commit()

    def make_context(invocation_id: str, **overrides) -> ToolInvocationContext:
        fields = {
            "workspace_id": workspace_id,
            "origin": "test",
            "root_run_id": None,
            "run_id": None,
            "invocation_id": invocation_id,
            "execution_user_id": actor_id,
            "access_source": "console",
            "deadline_at": utc_now() + timedelta(seconds=30),
            "idempotency_key": invocation_id,
        }
        fields.update(overrides)
        return ToolInvocationContext(**fields)

    async def queue_invocation(
        context: ToolInvocationContext,
        snap=snapshot,
    ) -> object:
        async with get_session_factory()() as db:
            invocation = await queue_tool_invocation(db, snap, {}, context)
            await db.commit()
            return invocation

    # Unknown invocation id (tool_runtime.py:116).
    try:
        await execute_tool_invocation("missing-invocation-id", settings, "edge-unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown invocation id must raise ValueError.")

    # Context contract rejections (tool_runtime.py:511, 513, 515, 517).
    async with get_session_factory()() as db:
        async def expect_context_error(
            context: ToolInvocationContext,
            fragment: str,
        ) -> None:
            try:
                await queue_tool_invocation(db, snapshot, {}, context)
            except ValueError as exc:
                assert fragment in str(exc), (fragment, str(exc))
            else:
                raise AssertionError(f"Context accepted: {context!r}")

        await expect_context_error(
            make_context("ctx-run", origin="test", root_run_id="r", run_id="r"),
            "cannot belong to a Run",
        )
        await expect_context_error(
            make_context("ctx-runless", origin="agent", root_run_id=None, run_id=None),
            "require Run IDs",
        )
        await expect_context_error(
            make_context("ctx-source", access_source="ssh"),
            "access source is invalid",
        )
        await expect_context_error(
            make_context("ctx-key", idempotency_key=""),
            "identity is invalid",
        )
        await db.rollback()

    # Idempotency reuse with different data (tool_runtime.py:91).
    async with get_session_factory()() as db:
        conflict_context = make_context(
            "conflict-1",
            idempotency_key="conflict-key-1",
        )
        await queue_tool_invocation(db, snapshot, {}, conflict_context)
        drifted = ToolInvocationContext(
            **{
                **conflict_context.__dict__,
                "execution_user_id": "another-user",
            }
        )
        try:
            await queue_tool_invocation(db, snapshot, {}, drifted)
        except ToolInvocationConflict:
            pass
        else:
            raise AssertionError(
                "Reused idempotency key with different data must conflict."
            )
        await db.commit()

    # Awaiting approval short-circuits (tool_runtime.py:120).
    approval_snapshot = dataclasses.replace(snapshot, approval=TOOL_APPROVAL_EACH_CALL)
    approval_invocation = await queue_invocation(
        make_context("edge-approval"),
        snap=approval_snapshot,
    )
    approval_result = await execute_tool_invocation(
        approval_invocation.id,
        settings,
        "edge-approval-worker",
    )
    assert approval_result.error_code == "approval_required"

    # Invalid snapshot payload (tool_runtime.py:124-125, 489).
    async with get_session_factory()() as db:
        invocation = await queue_tool_invocation(
            db,
            snapshot,
            {},
            make_context("edge-bad-snapshot"),
        )
        invocation.policy_snapshot = {
            "tool_snapshot": tool_snapshot_payload(snapshot),
            "deadline_at": 12345,
        }
        await tool_repository.save_tool_invocation(db, invocation)
        await db.commit()
        invocation_id = invocation.id
    bad_snapshot = await execute_tool_invocation(
        invocation_id,
        settings,
        "edge-bad-snapshot-worker",
    )
    assert bad_snapshot.error_code == "invalid_tool_snapshot"

    # Naive stored deadline (tool_runtime.py:124-125, 492).
    async with get_session_factory()() as db:
        invocation = await queue_tool_invocation(
            db,
            snapshot,
            {},
            make_context("edge-naive-deadline"),
        )
        invocation.policy_snapshot = {
            "tool_snapshot": tool_snapshot_payload(snapshot),
            "deadline_at": "2026-08-17T00:00:00",
        }
        await tool_repository.save_tool_invocation(db, invocation)
        await db.commit()
        invocation_id = invocation.id
    naive_deadline = await execute_tool_invocation(
        invocation_id,
        settings,
        "edge-naive-deadline-worker",
    )
    assert naive_deadline.error_code == "invalid_tool_snapshot"

    # Invalid stored arguments (tool_runtime.py:161-162).
    async with get_session_factory()() as db:
        invocation = await queue_tool_invocation(
            db,
            snapshot,
            {},
            make_context("edge-bad-args"),
        )
        invocation.arguments = {"unexpected": 1}
        await tool_repository.save_tool_invocation(db, invocation)
        await db.commit()
        invocation_id = invocation.id
    bad_args = await execute_tool_invocation(
        invocation_id,
        settings,
        "edge-bad-args-worker",
    )
    assert bad_args.error_code == "invalid_tool_arguments"

    # Deadline already expired (tool_runtime.py:169).
    deadline_invocation = await queue_invocation(
        make_context(
            "edge-deadline",
            deadline_at=utc_now() - timedelta(seconds=5),
        )
    )
    expired = await execute_tool_invocation(
        deadline_invocation.id,
        settings,
        "edge-deadline-worker",
    )
    assert expired.error_code == "tool_deadline_exceeded"

    # Crashed pure Tool whose attempts are exhausted (tool_runtime.py:148).
    async with get_session_factory()() as db:
        invocation = await queue_tool_invocation(
            db,
            snapshot,
            {},
            make_context("edge-crashed-safe"),
        )
        invocation.status = "running"
        invocation.attempts = invocation.max_attempts
        invocation.worker_task_id = "edge-crashed-safe-worker"
        invocation.lease_expires_at = utc_now() - timedelta(seconds=1)
        invocation.started_at = invocation.lease_expires_at
        await tool_repository.save_tool_invocation(db, invocation)
        await db.commit()
        invocation_id = invocation.id
    exhausted = await execute_tool_invocation(
        invocation_id,
        settings,
        "edge-crashed-safe-worker-2",
    )
    assert exhausted.error_code == "tool_attempts_exhausted"

    # Claim conflict with a live row (tool_runtime.py:184-188, 194).
    async with get_session_factory()() as db:
        invocation = await queue_tool_invocation(
            db,
            snapshot,
            {},
            make_context("edge-claim-conflict"),
        )
        invocation.status = "approved"
        invocation.attempts = invocation.max_attempts
        await tool_repository.save_tool_invocation(db, invocation)
        await db.commit()
        invocation_id = invocation.id
    try:
        await execute_tool_invocation(
            invocation_id,
            settings,
            "edge-claim-conflict-worker",
        )
    except ToolInvocationBusy:
        pass
    else:
        raise AssertionError(
            "A non-claimable exhausted invocation must raise ToolInvocationBusy."
        )

    # Claim conflict where the row becomes terminal in between
    # (tool_runtime.py:189-193).
    terminal_invocation = await queue_invocation(make_context("edge-claim-terminal"))

    async def fake_claim(
        db,
        workspace_id,
        invocation_id,
        worker_task_id,
        now,
        lease_expires_at,
    ):
        row = await tool_repository.get_tool_invocation(db, workspace_id, invocation_id)
        assert row is not None
        row.status = "succeeded"
        row.result_data = {"iso8601": "2026-08-17T00:00:00+00:00"}
        row.result_summary = "Done."
        row.outcome = "confirmed"
        row.error_code = None
        row.error_message = None
        row.usage = {}
        row.finished_at = utc_now()
        await tool_repository.save_tool_invocation(db, row)
        return False

    with patch(
        "app.infrastructure.repositories.tools.claim_tool_invocation",
        new=fake_claim,
    ):
        replay = await execute_tool_invocation(
            terminal_invocation.id,
            settings,
            "edge-claim-terminal-worker",
        )
    assert replay.ok is True
    assert replay.summary == "Done."

    # Adapter kind mismatch (tool_runtime.py:198).
    mismatch_invocation = await queue_invocation(make_context("edge-mismatch"))

    class MismatchAdapter:
        kind = "python"

        async def invoke(self, snapshot, arguments, context):
            raise AssertionError("A mismatched adapter must not run.")

    mismatch = await execute_tool_invocation(
        mismatch_invocation.id,
        settings,
        "edge-mismatch-worker",
        adapter=MismatchAdapter(),
    )
    assert mismatch.error_code == "tool_adapter_mismatch"

    # Provider timeout (tool_runtime.py:226-231).
    timeout_invocation = await queue_invocation(make_context("edge-timeout"))

    class TimeoutAdapter:
        kind = "builtin"

        async def invoke(self, snapshot, arguments, context):
            raise TimeoutError("timed out")

    timed_out = await execute_tool_invocation(
        timeout_invocation.id,
        settings,
        "edge-timeout-worker",
        adapter=TimeoutAdapter(),
    )
    assert timed_out.error_code == "tool_deadline_exceeded"

    # Provider exception (tool_runtime.py:232-237).
    boom_invocation = await queue_invocation(make_context("edge-boom"))

    class ExplodingAdapter:
        kind = "builtin"

        async def invoke(self, snapshot, arguments, context):
            raise RuntimeError("boom")

    exploded = await execute_tool_invocation(
        boom_invocation.id,
        settings,
        "edge-boom-worker",
        adapter=ExplodingAdapter(),
    )
    assert exploded.error_code == "tool_execution_failed"

    # Result cannot be stored because the row vanished (tool_runtime.py:252).
    deleted_invocation = await queue_invocation(make_context("edge-deleted"))

    class DeletingAdapter:
        kind = "builtin"

        async def invoke(self, snapshot, arguments, context):
            async with get_session_factory()() as other:
                row = await other.get(ToolInvocationOrm, deleted_invocation.id)
                assert row is not None
                await other.delete(row)
                await other.commit()
            return ToolRuntimeResult(
                ok=True,
                data={"iso8601": "2026-08-17T00:00:00+00:00"},
                summary="Done.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )

    vanished = await execute_tool_invocation(
        deleted_invocation.id,
        settings,
        "edge-deleted-worker",
        adapter=DeletingAdapter(),
    )
    assert vanished.error_code == "tool_result_not_persisted"

    # Finalize cannot save because the row is no longer running
    # (tool_runtime.py:267).
    mutated_invocation = await queue_invocation(make_context("edge-mutated"))

    class MutatingAdapter:
        kind = "builtin"

        async def invoke(self, snapshot, arguments, context):
            async with get_session_factory()() as other:
                row = await other.get(ToolInvocationOrm, mutated_invocation.id)
                assert row is not None
                row.status = "queued"
                row.worker_task_id = None
                row.lease_expires_at = None
                await other.commit()
            return ToolRuntimeResult(
                ok=True,
                data={"iso8601": "2026-08-17T00:00:00+00:00"},
                summary="Done.",
                error_code=None,
                error_message=None,
                outcome="confirmed",
                usage={},
            )

    lost = await execute_tool_invocation(
        mutated_invocation.id,
        settings,
        "edge-mutated-worker",
        adapter=MutatingAdapter(),
    )
    assert lost.error_code == "tool_result_not_persisted"

    # Live-state helpers (tool_runtime.py:451-460).
    async def set_policy(**fields) -> object:
        async with get_session_factory()() as db:
            policy = await tool_repository.get_tool_policy(db, workspace_id, tool_id)
            assert policy is not None
            expected = policy.revision
            policy.revision += 1
            for key, value in fields.items():
                setattr(policy, key, value)
            policy.updated_at = utc_now()
            assert (
                await tool_repository.update_tool_policy_if_revision(
                    db,
                    policy,
                    expected,
                )
                is not None
            )
            current_tool = await tool_repository.get_tool(db, workspace_id, tool_id)
            current_source = await tool_repository.get_tool_source(
                db,
                workspace_id,
                source_id,
            )
            current_version = await tool_repository.get_tool_version(
                db,
                workspace_id,
                current_tool.current_version_id or "",
            )
            assert (
                current_tool is not None
                and current_source is not None
                and current_version is not None
            )
            built = build_tool_snapshot(
                current_tool,
                current_source,
                current_version,
                policy,
                actor_id,
            )
            await db.commit()
            return built

    async def preflight(
        snap,
        *,
        origin="test",
        execution_user_id=None,
        access_source="console",
    ) -> ToolRuntimeResult | None:
        async with get_session_factory()() as db:
            return await preflight_tool_snapshot(
                db,
                snap,
                origin=origin,
                workspace_id=workspace_id,
                execution_user_id=execution_user_id or actor_id,
                access_source=access_source,
            )

    # Live-state happy path (tool_runtime.py:451-460).
    assert await preflight(snapshot) is None

    # Live-state: unavailable tool (tool_runtime.py:289).
    async with get_session_factory()() as db:
        current_tool = await tool_repository.get_tool(db, workspace_id, tool_id)
        assert current_tool is not None
        current_tool.availability = "unavailable"
        await tool_repository.save_tool(db, current_tool)
        await db.commit()
    failure = await preflight(snapshot)
    assert failure is not None and failure.error_code == "tool_unavailable"
    async with get_session_factory()() as db:
        current_tool = await tool_repository.get_tool(db, workspace_id, tool_id)
        assert current_tool is not None
        current_tool.availability = "available"
        await tool_repository.save_tool(db, current_tool)
        await db.commit()

    # Live-state: definition drift (tool_runtime.py:310).
    async with get_session_factory()() as db:
        current_tool = await tool_repository.get_tool(db, workspace_id, tool_id)
        assert current_tool is not None
        current_tool.function_name = "renamed_current_time"
        await tool_repository.save_tool(db, current_tool)
        await db.commit()
    failure = await preflight(snapshot)
    assert failure is not None and failure.error_code == "tool_definition_changed"
    async with get_session_factory()() as db:
        current_tool = await tool_repository.get_tool(db, workspace_id, tool_id)
        assert current_tool is not None
        current_tool.function_name = "current_time"
        await tool_repository.save_tool(db, current_tool)
        await db.commit()

    # Live-state: disabled policy approval (tool_runtime.py:336).
    disabled_snapshot = await set_policy(
        approval="disabled",
        effect="pure",
        allowed_access_sources=["console", "public", "api"],
        workflow_callable=True,
        parallel_safe=True,
    )
    failure = await preflight(disabled_snapshot)
    assert failure is not None and failure.error_code == "tool_disabled"

    # Live-state: console outside allowed sources (tool_runtime.py:338).
    console_denied = await set_policy(
        approval="auto",
        effect="pure",
        allowed_access_sources=["api"],
        workflow_callable=True,
        parallel_safe=True,
    )
    failure = await preflight(console_denied)
    assert failure is not None and failure.error_code == "tool_access_source_denied"

    # Live-state: unsafe effect through a public source (tool_runtime.py:343).
    public_denied = await set_policy(
        approval="auto",
        effect="external_write",
        allowed_access_sources=["console", "public"],
        workflow_callable=True,
        parallel_safe=True,
    )
    failure = await preflight(public_denied, access_source="public")
    assert failure is not None and failure.error_code == "tool_access_source_denied"

    # Live-state: not workflow callable (tool_runtime.py:345).
    agent_only = await set_policy(
        approval="auto",
        effect="pure",
        allowed_access_sources=["console", "public", "api"],
        workflow_callable=False,
        parallel_safe=True,
    )
    failure = await preflight(agent_only, origin="workflow", access_source="api")
    assert failure is not None and failure.error_code == "tool_not_workflow_callable"

    # Live-state: workflow-only Tool from an Agent (tool_runtime.py:347).
    async with get_session_factory()() as db:
        inline_tool = next(
            item
            for item in await tool_repository.list_tools(db, workspace_id)
            if item.stable_key == "inline_python"
        )
        inline_source = await tool_repository.get_tool_source(
            db,
            workspace_id,
            inline_tool.source_id,
        )
        inline_version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            inline_tool.current_version_id or "",
        )
        inline_policy = await tool_repository.get_tool_policy(
            db,
            workspace_id,
            inline_tool.id,
        )
        assert (
            inline_source is not None
            and inline_version is not None
            and inline_policy is not None
        )
        inline_snapshot = build_tool_snapshot(
            inline_tool,
            inline_source,
            inline_version,
            inline_policy,
            actor_id,
        )
        await db.commit()
    failure = await preflight(inline_snapshot)
    assert failure is not None and failure.error_code == "tool_not_agent_callable"

    # Restore the known-good policy for the remaining branches.
    snapshot = await set_policy(
        approval="auto",
        effect="pure",
        allowed_access_sources=["console", "public", "api"],
        workflow_callable=True,
        parallel_safe=True,
    )

    # Live-state: revoked binding access (tool_runtime.py:389).
    async with get_session_factory()() as db:
        current_tool = await tool_repository.get_tool(db, workspace_id, tool_id)
        current_source = await tool_repository.get_tool_source(
            db,
            workspace_id,
            source_id,
        )
        current_version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            current_tool.current_version_id or "",
        )
        current_policy = await tool_repository.get_tool_policy(
            db,
            workspace_id,
            tool_id,
        )
        assert (
            current_source is not None
            and current_version is not None
            and current_policy is not None
        )
        stranger_snapshot = build_tool_snapshot(
            current_tool,
            current_source,
            current_version,
            current_policy,
            stranger_id,
        )
        await db.commit()
    failure = await preflight(stranger_snapshot)
    assert failure is not None and failure.error_code == "tool_access_revoked"

    # Live-state: revoked execution access (tool_runtime.py:410).
    failure = await preflight(snapshot, execution_user_id=stranger_id)
    assert (
        failure is not None
        and failure.error_code == "tool_execution_access_revoked"
    )

    # Live-state: MCP server unavailable (tool_runtime.py:417-427).
    async with get_session_factory()() as db:
        mcp_server = await mcp_repository.create_mcp_server(
            db,
            McpServer(
                workspace_id=workspace_id,
                name="Edge MCP",
                url="https://tools.example.com/mcp",
                tools=[],
                status="active",
                created_by_user_id=actor_id,
            ),
        )
        mcp_source = await tool_repository.save_tool_source(
            db,
            ToolSource(
                workspace_id=workspace_id,
                mcp_server_id=mcp_server.id,
                kind="mcp",
                name="Edge MCP",
                status="active",
                created_by_user_id=actor_id,
            ),
        )
        mcp_tool = await tool_repository.save_tool(
            db,
            Tool(
                workspace_id=workspace_id,
                source_id=mcp_source.id,
                kind="mcp",
                stable_key="edge-lookup",
                function_name="edge_lookup",
                status="active",
                availability="available",
                created_by_user_id=actor_id,
            ),
        )
        mcp_version = await tool_repository.save_tool_version(
            db,
            ToolVersion(
                workspace_id=workspace_id,
                tool_id=mcp_tool.id,
                revision=1,
                display_name="Edge lookup",
                input_schema={"type": "object"},
                execution_spec={
                    "server_id": mcp_server.id,
                    "tool_name": "edge_lookup",
                },
                definition_hash="b" * 64,
                created_by_user_id=actor_id,
            ),
        )
        mcp_tool.current_version_id = mcp_version.id
        await tool_repository.save_tool(db, mcp_tool)
        mcp_policy = await tool_repository.save_tool_policy(
            db,
            ToolPolicy(
                workspace_id=workspace_id,
                tool_id=mcp_tool.id,
                tool_version_id=mcp_version.id,
                definition_hash="b" * 64,
                approval="auto",
                effect="external_read",
                allowed_access_sources=["console"],
                reviewed_by_user_id=actor_id,
            ),
        )
        mcp_snapshot = build_tool_snapshot(
            mcp_tool,
            mcp_source,
            mcp_version,
            mcp_policy,
            actor_id,
        )
        mcp_server_id = mcp_server.id
        mcp_source_id = mcp_source.id
        await db.commit()
    async with get_session_factory()() as db:
        mcp_server = await mcp_repository.get_mcp_server_by_id(db, mcp_server_id)
        assert mcp_server is not None
        mcp_server.status = "disabled"
        await mcp_repository.save_mcp_server(db, mcp_server)
        await db.commit()
    failure = await preflight(mcp_snapshot)
    assert failure is not None and failure.error_code == "tool_unavailable"
    # Live-state: MCP snapshot bound to a source without an MCP server
    # (tool_runtime.py:419-420, 422-427).
    async with get_session_factory()() as db:
        ghost_source = next(
            source
            for source in await tool_repository.list_tool_sources(db, workspace_id)
            if source.kind == "python"
        )
        ghost_tool = await tool_repository.save_tool(
            db,
            Tool(
                workspace_id=workspace_id,
                source_id=ghost_source.id,
                kind="mcp",
                stable_key="ghost-lookup",
                function_name="ghost_lookup",
                status="active",
                availability="available",
                created_by_user_id=actor_id,
            ),
        )
        ghost_version = await tool_repository.save_tool_version(
            db,
            ToolVersion(
                workspace_id=workspace_id,
                tool_id=ghost_tool.id,
                revision=1,
                display_name="Ghost lookup",
                input_schema={"type": "object"},
                execution_spec={"tool_name": "ghost_lookup"},
                definition_hash="c" * 64,
                created_by_user_id=actor_id,
            ),
        )
        ghost_tool.current_version_id = ghost_version.id
        await tool_repository.save_tool(db, ghost_tool)
        ghost_policy = await tool_repository.save_tool_policy(
            db,
            ToolPolicy(
                workspace_id=workspace_id,
                tool_id=ghost_tool.id,
                tool_version_id=ghost_version.id,
                definition_hash="c" * 64,
                approval="auto",
                effect="external_read",
                allowed_access_sources=["console"],
                reviewed_by_user_id=actor_id,
            ),
        )
        ghost_snapshot = build_tool_snapshot(
            ghost_tool,
            ghost_source,
            ghost_version,
            ghost_policy,
            actor_id,
        )
        await db.commit()
    failure = await preflight(ghost_snapshot)
    assert failure is not None and failure.error_code == "tool_unavailable"


async def assert_mcp_source_management(workspace_id: str) -> None:
    from unittest.mock import AsyncMock, patch

    from fastapi import HTTPException

    from app.application.tool_management import (
        create_mcp_source,
        delete_source,
        list_sources,
        refresh_source,
        set_source_enabled,
        update_policy,
    )
    from app.infrastructure.config import Settings
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository
    from app.schemas.mcp import McpServerCreateRequest

    settings = Settings.from_env(require_bootstrap=False)
    discovery = SimpleNamespace(
        tools=[
            {
                "name": "lookup",
                "description": "Lookup a record.",
                "input_schema": {"type": "object", "additionalProperties": False},
            }
        ]
    )
    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        with patch(
            "app.shareddomain.tools.services.discover_mcp_tools",
            new=AsyncMock(return_value=discovery),
        ):
            created = await create_mcp_source(
                db,
                workspace_id,
                McpServerCreateRequest(
                    name="Runtime MCP",
                    transport="streamable_http",
                    url="https://tools.example.com/mcp",
                ),
                actor,
                "admin",
                settings,
            )
        assert created.kind == "mcp"
        source_id = created.id
        assert created.tool_count == 1
        listed = await list_sources(db, workspace_id, actor, "admin", 10, 0)
        assert source_id in {item.id for item in listed}
        with patch(
            "app.shareddomain.tools.services.discover_mcp_tools",
            new=AsyncMock(return_value=discovery),
        ):
            refreshed = await refresh_source(
                db,
                workspace_id,
                source_id,
                actor,
                "admin",
                settings,
            )
        assert refreshed.status == "active"
        disabled = await set_source_enabled(
            db,
            workspace_id,
            source_id,
            False,
            actor,
            "admin",
        )
        assert disabled.status == "disabled"
        enabled = await set_source_enabled(
            db,
            workspace_id,
            source_id,
            True,
            actor,
            "admin",
        )
        assert enabled.status == "active"
        try:
            await refresh_source(
                db,
                workspace_id,
                "missing-source",
                actor,
                "admin",
                settings,
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("A missing MCP source must 404.")
        tools = await tool_repository.list_tools(db, workspace_id)
        mcp_tool = next(
            item
            for item in tools
            if item.kind == "mcp" and item.source_id == source_id
        )
        updated = await update_policy(
            db,
            workspace_id,
            mcp_tool.id,
            "read_only",
            actor,
            "admin",
        )
        assert updated.approval == "auto"
        assert updated.effect == "external_read"
        builtin = next(item for item in tools if item.stable_key == "current_time")
        try:
            await update_policy(
                db,
                workspace_id,
                builtin.id,
                "read_only",
                actor,
                "admin",
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("Non-MCP Tool policy changes must 422.")
        await delete_source(db, workspace_id, source_id, actor, "admin")
        remaining = await tool_repository.list_tool_sources(db, workspace_id)
        assert source_id not in {
            item.id
            for item in remaining
            if item.kind == "mcp" and item.status == "active"
        }


async def assert_tool_management_branches(
    workspace_id: str,
    member_id: str,
) -> None:
    from unittest.mock import AsyncMock, patch

    from fastapi import HTTPException

    from app.application.tool_management import (
        create_python,
        delete_python,
        get_python_test,
        publish_python,
        queue_python_test,
        set_python_enabled,
        update_python_draft,
        upsert_permission,
    )
    from app.infrastructure.config import Settings
    from app.infrastructure.repositories import user as user_repository
    from app.schemas.tool import PythonToolCreateRequest, PythonToolDraftUpdateRequest

    settings = Settings.from_env(require_bootstrap=False)
    input_schema = {
        "type": "object",
        "properties": {"value": {"type": "string", "maxLength": 64}},
        "required": ["value"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {"value": {"type": "string", "maxLength": 64}},
        "required": ["value"],
        "additionalProperties": False,
    }
    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        created = await create_python(
            db,
            workspace_id,
            PythonToolCreateRequest(
                display_name="Branch tool",
                description="Branch coverage.",
                input_schema=input_schema,
                output_schema=output_schema,
                code="result = {'value': inputs['value']}",
            ),
            actor,
            "admin",
        )
        tool_id = created.id
        assert created.kind == "python"
        updated = await update_python_draft(
            db,
            workspace_id,
            tool_id,
            PythonToolDraftUpdateRequest(
                expected_revision=1,
                display_name="Branch tool",
                description="Branch coverage safely.",
                input_schema=input_schema,
                output_schema=output_schema,
                code="result = {'value': inputs['value'].upper()}",
            ),
            actor,
            "admin",
        )
        assert updated.revision == 2
        with patch(
            "app.application.tool_management.enqueue_tool_invocation",
            new_callable=AsyncMock,
        ) as dispatch:
            queued = await queue_python_test(
                db,
                workspace_id,
                tool_id,
                {"value": "nexa"},
                actor,
                "admin",
                settings,
            )
        assert queued.status == "queued"
        assert dispatch.await_count == 1
        assert dispatch.await_args.args[0] == queued.id
        try:
            await queue_python_test(
                db,
                workspace_id,
                tool_id,
                {},
                actor,
                "admin",
                settings,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("Invalid Tool test arguments must 422.")
        await db.commit()
        found = await get_python_test(
            db,
            workspace_id,
            tool_id,
            queued.id,
            actor,
            "admin",
        )
        assert found.id == queued.id
        try:
            await get_python_test(
                db,
                workspace_id,
                tool_id,
                "missing-invocation",
                actor,
                "admin",
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("A missing Tool test must 404.")
        published = await publish_python(
            db,
            workspace_id,
            tool_id,
            actor,
            "admin",
        )
        assert published.current_version_id
        disabled = await set_python_enabled(
            db,
            workspace_id,
            tool_id,
            False,
            actor,
            "admin",
        )
        assert disabled.status == "disabled"
        enabled = await set_python_enabled(
            db,
            workspace_id,
            tool_id,
            True,
            actor,
            "admin",
        )
        assert enabled.status == "active"
        granted = await upsert_permission(
            db,
            workspace_id,
            tool_id,
            member_id,
            "view",
            actor,
            "admin",
        )
        assert granted.permission == "view"
        assert granted.user.id == member_id
        await delete_python(db, workspace_id, tool_id, actor, "admin")
        await db.commit()


async def assert_workflow_tool_runtime(workspace_id: str) -> None:
    import dataclasses
    from datetime import datetime, timedelta
    from unittest.mock import patch

    from app.application.tool_runtime import ToolInvocationBusy
    from app.application.workflow_tool_runtime import (
        WorkflowToolRuntime,
        workflow_tool_invocation_identity,
    )
    from app.capabilities.llm.models import RegisteredModel
    from app.entities.agents import Agent as AgentEntity
    from app.entities.agents import AgentRun
    from app.entities.workflows import WorkflowRunDetail
    from app.infrastructure.config import Settings
    from app.infrastructure.model_utils import utc_now
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository
    from app.ports.tool_runtime import ToolRuntimeResult
    from app.shareddomain.tools.runtime import (
        TOOL_APPROVAL_EACH_CALL,
        build_tool_snapshot,
    )

    settings = Settings.from_env(require_bootstrap=False)

    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        tool = next(
            item
            for item in await tool_repository.list_tools(db, workspace_id)
            if item.stable_key == "current_time"
        )
        source = await tool_repository.get_tool_source(db, workspace_id, tool.source_id)
        version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            tool.current_version_id or "",
        )
        policy = await tool_repository.get_tool_policy(db, workspace_id, tool.id)
        assert source is not None and version is not None and policy is not None
        expected = policy.revision
        policy.revision += 1
        policy.approval = "auto"
        policy.effect = "pure"
        policy.allowed_access_sources = ["console", "public", "api"]
        policy.workflow_callable = True
        policy.parallel_safe = True
        policy.updated_at = utc_now()
        assert (
            await tool_repository.update_tool_policy_if_revision(
                db,
                policy,
                expected,
            )
            is not None
        )
        snapshot = build_tool_snapshot(tool, source, version, policy, actor.id)
        inline_tool = next(
            item
            for item in await tool_repository.list_tools(db, workspace_id)
            if item.stable_key == "inline_python"
        )
        inline_source = await tool_repository.get_tool_source(
            db,
            workspace_id,
            inline_tool.source_id,
        )
        inline_version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            inline_tool.current_version_id or "",
        )
        inline_policy = await tool_repository.get_tool_policy(
            db,
            workspace_id,
            inline_tool.id,
        )
        assert (
            inline_source is not None
            and inline_version is not None
            and inline_policy is not None
        )
        inline_snapshot = build_tool_snapshot(
            inline_tool,
            inline_source,
            inline_version,
            inline_policy,
            actor.id,
        )
        actor_id = actor.id
        tool_id = tool.id
        source_id = source.id
        await db.commit()

    run = AgentRun(
        id="wf-edge-run",
        workspace_id=workspace_id,
        agent_id="wf-edge-agent",
        execution_user_id=actor_id,
        access_source="api",
    )
    async with get_session_factory()() as db:
        model = RegisteredModel(
            workspace_id=workspace_id,
            name="Edge Workflow Model",
            provider="model_custom_provider",
            provider_type="openai_compatible",
            api_base="",
            model_type="LLM",
            model_name="edge-model",
            status="active",
            created_by_user_id=actor_id,
        )
        db.add(model)
        await db.flush()
        await agent_repository.save_agent(
            db,
            AgentEntity(
                id="wf-edge-agent",
                workspace_id=workspace_id,
                name="Edge Agent",
                model_id=model.id,
                created_by_user_id=actor_id,
            ),
        )
        await agent_repository.save_agent_run(db, run)
        await db.commit()
    detail = WorkflowRunDetail(
        id="wf-edge-detail",
        run_id=run.id,
        deadline_at=datetime.now() + timedelta(seconds=30),
    )
    lease_lost = asyncio.Event()
    runtime = WorkflowToolRuntime(
        run,
        detail,
        [snapshot, inline_snapshot],
        "wf-edge-worker",
        settings,
        lease_lost,
    )

# Identity helper (workflow_tool_runtime.py:31-35).
    invocation_id, idempotency_key = workflow_tool_invocation_identity(
        run.id,
        "node-1",
        "call-1",
    )
    assert invocation_id == "node-1:call-1"
    assert len(idempotency_key) == 64
    try:
        workflow_tool_invocation_identity(run.id, "x" * 300, "c")
    except ValueError:
        pass
    else:
        raise AssertionError("Oversized Workflow identity must raise.")

# Lookup helpers (workflow_tool_runtime.py:61-68).
    assert runtime.get_by_function("current_time") is snapshot
    assert runtime.get_by_function("missing") is None
    assert runtime.get_by_reference(snapshot.tool_id, snapshot.version_id) is snapshot
    try:
        runtime.get_by_reference("missing-tool", "missing-version")
    except ValueError:
        pass
    else:
        raise AssertionError("Missing Workflow snapshot must raise.")

# Duplicate function names (workflow_tool_runtime.py:57-58).
    try:
        WorkflowToolRuntime(
            run,
            detail,
            [snapshot, snapshot],
            "wf-edge-worker",
            settings,
            lease_lost,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate Workflow Tool function names must raise.")

# LLM calls to direct-only Tools (workflow_tool_runtime.py:77-81).
    try:
        await runtime.invoke(
            inline_snapshot,
            "node-llm",
            "llm:1",
            {"code": "x = 1", "inputs": {}},
        )
    except RuntimeError as exc:
        assert "direct node" in str(exc)
    else:
        raise AssertionError("An LLM call to a direct-only Tool must raise.")

# Invalid parameters (workflow_tool_runtime.py:126-131).
    invalid = await runtime.invoke(snapshot, "node-bad", "call-bad", {"nope": 1})
    assert invalid.is_error is True
    assert "Tool parameters are invalid" in invalid.content

# Happy path through the real runtime (workflow_tool_runtime.py:94-154).
    completed = await runtime.invoke(snapshot, "node-ok", "call-ok", {})
    assert completed.is_error is False
    assert "iso8601" in completed.content

# Reused identity with drifted stored data conflicts
    # (workflow_tool_runtime.py:124-125).
    _node_id, drifted_key = workflow_tool_invocation_identity(
        run.id,
        "node-replay",
        "call-replay",
    )
    await runtime.invoke(snapshot, "node-replay", "call-replay", {})
    async with get_session_factory()() as db:
        stored = await tool_repository.get_tool_invocation_by_idempotency_key(
            db,
            workspace_id,
            drifted_key,
        )
        assert stored is not None
        stored.arguments_hash = "d" * 64
        await tool_repository.save_tool_invocation(db, stored)
        await db.commit()
    try:
        await runtime.invoke(snapshot, "node-replay", "call-replay", {})
    except RuntimeError as exc:
        assert "idempotency" in str(exc)
    else:
        raise AssertionError("A drifted Workflow identity must conflict.")

# Approval-required Tools cannot run in Workflows
    # (workflow_tool_runtime.py:132-133).
    approval_snapshot = dataclasses.replace(snapshot, approval=TOOL_APPROVAL_EACH_CALL)
    try:
        await runtime.invoke(
            approval_snapshot,
            "node-approval",
            "call-approval",
            {},
        )
    except RuntimeError as exc:
        assert "approval" in str(exc)
    else:
        raise AssertionError("An approval-required Workflow Tool must raise.")

# Lost lease (workflow_tool_runtime.py:94-95).
    lost = asyncio.Event()
    lost.set()
    lost_runtime = WorkflowToolRuntime(
        run,
        detail,
        [snapshot],
        "wf-edge-worker",
        settings,
        lost,
    )
    try:
        await lost_runtime.invoke(snapshot, "node-lost", "call-lost", {})
    except RuntimeError as exc:
        assert "lease" in str(exc)
    else:
        raise AssertionError("A lost Workflow lease must raise.")

# Busy provider is retried until success (workflow_tool_runtime.py:134-146).
    busy_sequence = [
        ToolInvocationBusy("provider busy"),
        ToolRuntimeResult(
            ok=True,
            data={"iso8601": "2026-08-17T00:00:00+00:00"},
            summary="Done.",
            error_code=None,
            error_message=None,
            outcome="confirmed",
            usage={},
        ),
    ]

    async def flaky_execute(*_args, **_kwargs):
        item = busy_sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    with patch(
        "app.application.workflow_tool_runtime.execute_tool_invocation",
        new=flaky_execute,
    ):
        retried = await runtime.invoke(snapshot, "node-busy", "call-busy", {})
    assert retried.is_error is False

# Busy provider with an expired deadline fails fast
    # (workflow_tool_runtime.py:143-145).
    past_detail = WorkflowRunDetail(
        id="wf-edge-detail-past",
        run_id=run.id,
        deadline_at=utc_now() - timedelta(seconds=5),
    )
    past_runtime = WorkflowToolRuntime(
        run,
        past_detail,
        [snapshot],
        "wf-edge-worker",
        settings,
        asyncio.Event(),
    )

    async def always_busy(*_args, **_kwargs):
        raise ToolInvocationBusy("provider busy")

    with patch(
        "app.application.workflow_tool_runtime.execute_tool_invocation",
        new=always_busy,
    ):
        try:
            await past_runtime.invoke(snapshot, "node-past", "call-past", {})
        except RuntimeError as exc:
            assert "provider busy" in str(exc)
        else:
            raise AssertionError("An expired busy retry must raise.")

# Uncertain outcome raises (workflow_tool_runtime.py:148-151).
    async def uncertain_execute(*_args, **_kwargs):
        return ToolRuntimeResult(
            ok=False,
            data=None,
            summary="Uncertain.",
            error_code="tool_outcome_uncertain",
            error_message="outcome unknown",
            outcome="uncertain",
            usage={},
        )

    with patch(
        "app.application.workflow_tool_runtime.execute_tool_invocation",
        new=uncertain_execute,
    ):
        try:
            await runtime.invoke(snapshot, "node-uncertain", "call-uncertain", {})
        except RuntimeError as exc:
            assert "outcome unknown" in str(exc)
        else:
            raise AssertionError("An uncertain Workflow Tool outcome must raise.")

# Approval-required result raises (workflow_tool_runtime.py:152-153).
    async def approval_execute(*_args, **_kwargs):
        return ToolRuntimeResult(
            ok=False,
            data=None,
            summary="Approval required.",
            error_code="approval_required",
            error_message="Tool invocation requires approval.",
            outcome="confirmed",
            usage={},
        )

    with patch(
        "app.application.workflow_tool_runtime.execute_tool_invocation",
        new=approval_execute,
    ):
        try:
            await runtime.invoke(snapshot, "node-approval-2", "call-approval-2", {})
        except RuntimeError as exc:
            assert "approval" in str(exc)
        else:
            raise AssertionError("An approval-required Workflow result must raise.")

    # Serialized (non-parallel-safe) invocation (workflow_tool_runtime.py:84-85).
    async with get_session_factory()() as db:
        serial_policy = await tool_repository.get_tool_policy(
            db,
            workspace_id,
            tool_id,
        )
        assert serial_policy is not None
        expected = serial_policy.revision
        serial_policy.revision += 1
        serial_policy.parallel_safe = False
        serial_policy.updated_at = utc_now()
        assert (
            await tool_repository.update_tool_policy_if_revision(
                db,
                serial_policy,
                expected,
            )
            is not None
        )
        current_tool = await tool_repository.get_tool(db, workspace_id, tool_id)
        current_source = await tool_repository.get_tool_source(
            db,
            workspace_id,
            source_id,
        )
        current_version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            current_tool.current_version_id or "",
        )
        assert (
            current_tool is not None
            and current_source is not None
            and current_version is not None
        )
        serial_snapshot = build_tool_snapshot(
            current_tool,
            current_source,
            current_version,
            serial_policy,
            actor_id,
        )
        await db.commit()
    serialized = await runtime.invoke(
        serial_snapshot,
        "node-serial",
        "call-serial",
        {},
    )
    assert serialized.is_error is False


async def assert_tool_adapters(workspace_id: str) -> None:
    import dataclasses
    import json
    from datetime import timedelta
    from unittest.mock import AsyncMock, patch

    from app.application.tool_adapters import (
        BuiltinToolAdapter,
        McpToolAdapter,
        PythonToolAdapter,
        build_tool_adapter,
    )
    from app.entities.tools import McpServer
    from app.infrastructure.code_sandbox import (
        ArtifactSandboxResult,
        WorkflowSandboxBusyError,
        WorkflowSandboxError,
        WorkflowSandboxResult,
    )
    from app.infrastructure.config import Settings
    from app.infrastructure.model_utils import utc_now
    from app.infrastructure.repositories import tools as tool_repository
    from app.infrastructure.repositories import user as user_repository
    from app.ports.mcp import McpClientError
    from app.ports.tool_runtime import ToolAdapterBusy, ToolInvocationContext
    from app.shareddomain.tools.runtime import build_tool_snapshot

    settings = Settings.from_env(require_bootstrap=False)
    context = ToolInvocationContext(
        workspace_id=workspace_id,
        origin="workflow",
        root_run_id="r",
        run_id="r",
        invocation_id="adapter-inv",
        execution_user_id="admin",
        access_source="console",
        deadline_at=utc_now() + timedelta(seconds=30),
        idempotency_key="adapter-inv",
    )

    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        tool = next(
            item
            for item in await tool_repository.list_tools(db, workspace_id)
            if item.stable_key == "current_time"
        )
        source = await tool_repository.get_tool_source(db, workspace_id, tool.source_id)
        version = await tool_repository.get_tool_version(
            db,
            workspace_id,
            tool.current_version_id or "",
        )
        policy = await tool_repository.get_tool_policy(db, workspace_id, tool.id)
        assert source is not None and version is not None and policy is not None
        snapshot = build_tool_snapshot(tool, source, version, policy, actor.id)
        actor_id = actor.id
        await db.commit()

    mcp_server = McpServer(
        workspace_id=workspace_id,
        name="Adapter MCP",
        transport="streamable_http",
        url="https://tools.example.com/mcp",
        tools=[],
        status="active",
        created_by_user_id=actor_id,
    )

    # Factory selection (tool_adapters.py:161-167).
    assert isinstance(build_tool_adapter(snapshot, settings), BuiltinToolAdapter)
    python_snapshot = dataclasses.replace(
        snapshot,
        kind="python",
        execution_spec={"code": "result = {'value': 1}"},
    )
    assert isinstance(build_tool_adapter(python_snapshot, settings), PythonToolAdapter)
    mcp_snapshot = dataclasses.replace(
        snapshot,
        kind="mcp",
        execution_spec={"tool_name": "lookup"},
    )
    assert isinstance(
        build_tool_adapter(mcp_snapshot, settings, mcp_server),
        McpToolAdapter,
    )
    try:
        build_tool_adapter(dataclasses.replace(snapshot, kind="unknown"), settings)
    except ValueError:
        pass
    else:
        raise AssertionError("An unknown Tool kind must raise.")

    # Builtin current_time (tool_adapters.py:36-46).
    builtin = BuiltinToolAdapter(settings)
    result = await builtin.invoke(snapshot, {}, context)
    assert result.ok is True
    assert "iso8601" in result.data
    artifact_snapshot = dataclasses.replace(
        snapshot,
        execution_spec={"builtin": "python_artifact"},
    )
    artifact_content = b"<html><body>ready</body></html>"
    with patch(
        "app.application.tool_adapters.execute_artifact_code",
        new=AsyncMock(
            return_value=ArtifactSandboxResult(
                content=artifact_content,
                format="html",
                filename="page.html",
                size_bytes=len(artifact_content),
                sha256="ignored-by-adapter",
                stdout="",
                stderr="",
                exit_code=0,
            )
        ),
    ) as artifact_sandbox:
        result = await builtin.invoke(
            artifact_snapshot,
            {
                "code": "open(output_path, 'w').write('ready')",
                "format": "html",
                "filename": "page.html",
                "skills": ["documents"],
            },
            context,
        )
    assert result.ok is True
    assert result.data["filename"] == "page.html"
    assert result.data["download_url"].startswith("/api/v1/artifacts/")
    assert result.usage == {"exit_code": 0, "size_bytes": len(artifact_content)}
    assert artifact_sandbox.await_count == 1
    with patch(
        "app.application.tool_adapters.execute_artifact_code",
        new=AsyncMock(side_effect=WorkflowSandboxError("NameError: missing value")),
    ):
        result = await builtin.invoke(
            artifact_snapshot,
            {"code": "missing", "format": "html", "filename": "page.html"},
            dataclasses.replace(context, idempotency_key="adapter-failed"),
        )
    assert result.ok is False
    assert result.error_code == "python_artifact_failed"
    assert "NameError" in result.error_message
    # Unsupported builtin (tool_adapters.py:47-48).
    result = await builtin.invoke(
        dataclasses.replace(snapshot, execution_spec={"builtin": "other"}),
        {},
        context,
    )
    assert result.ok is False
    assert result.error_code == "unsupported_builtin"
    # Inline Python (tool_adapters.py:49-54, 59-67).
    inline_snapshot = dataclasses.replace(
        snapshot,
        execution_spec={"builtin": "inline_python"},
    )
    with patch(
        "app.application.tool_adapters.execute_workflow_code",
        new=AsyncMock(
            return_value=WorkflowSandboxResult(
                result={"result": 42},
                stdout="",
                stderr="",
                exit_code=0,
            )
        ),
    ) as sandbox:
        result = await builtin.invoke(
            inline_snapshot,
            {"code": "result = {'result': 42}", "inputs": {}},
            context,
        )
    assert result.ok is True
    assert result.data == {"result": {"result": 42}}
    assert result.usage == {"exit_code": 0}
    assert sandbox.await_count == 1
    # Inline Python busy (tool_adapters.py:55-56).
    with patch(
        "app.application.tool_adapters.execute_workflow_code",
        new=AsyncMock(side_effect=WorkflowSandboxBusyError("busy")),
    ):
        try:
            await builtin.invoke(
                inline_snapshot,
                {"code": "result = 1", "inputs": {}},
                context,
            )
        except ToolAdapterBusy:
            pass
        else:
            raise AssertionError("A busy sandbox must raise ToolAdapterBusy.")
    # Inline Python failure (tool_adapters.py:57-58).
    with patch(
        "app.application.tool_adapters.execute_workflow_code",
        new=AsyncMock(side_effect=WorkflowSandboxError("failed")),
    ):
        result = await builtin.invoke(
            inline_snapshot,
            {"code": "result = 1", "inputs": {}},
            context,
        )
    assert result.ok is False
    assert result.error_code == "python_execution_failed"
    # Python adapter invalid code (tool_adapters.py:83-85).
    python = PythonToolAdapter(settings)
    result = await python.invoke(
        dataclasses.replace(snapshot, kind="python", execution_spec={}),
        {},
        context,
    )
    assert result.ok is False
    assert result.error_code == "invalid_python_tool"
    # Python adapter happy path (tool_adapters.py:86-87, 95-103).
    with patch(
        "app.application.tool_adapters.execute_workflow_code",
        new=AsyncMock(
            return_value=WorkflowSandboxResult(
                result={"value": "NEXA"},
                stdout="",
                stderr="",
                exit_code=0,
            )
        ),
    ):
        result = await python.invoke(python_snapshot, {"value": "nexa"}, context)
    assert result.ok is True
    assert result.data == {"value": "NEXA"}
    assert result.usage == {"exit_code": 0}
    # Python adapter busy (tool_adapters.py:88-89).
    with patch(
        "app.application.tool_adapters.execute_workflow_code",
        new=AsyncMock(side_effect=WorkflowSandboxBusyError("busy")),
    ):
        try:
            await python.invoke(python_snapshot, {"value": "nexa"}, context)
        except ToolAdapterBusy:
            pass
        else:
            raise AssertionError("A busy sandbox must raise ToolAdapterBusy.")
    # Python adapter failure (tool_adapters.py:90-94).
    with patch(
        "app.application.tool_adapters.execute_workflow_code",
        new=AsyncMock(side_effect=WorkflowSandboxError("failed")),
    ):
        result = await python.invoke(python_snapshot, {"value": "nexa"}, context)
    assert result.ok is False
    assert result.error_code == "python_execution_failed"
    # MCP adapter missing tool name (tool_adapters.py:119-121).
    mcp = McpToolAdapter(settings, mcp_server)
    result = await mcp.invoke(
        dataclasses.replace(snapshot, kind="mcp", execution_spec={}),
        {},
        context,
    )
    assert result.ok is False
    assert result.error_code == "invalid_mcp_tool"
    # MCP adapter happy path (tool_adapters.py:123-129, 141-145, 145-153).
    with patch(
        "app.application.tool_adapters.call_mcp_tool",
        new=AsyncMock(return_value=('{"ok": true}', False)),
    ) as call:
        result = await mcp.invoke(mcp_snapshot, {}, context)
    assert result.ok is True
    assert result.data == {"ok": True}
    assert call.await_count == 1
    # MCP adapter non-JSON error content (tool_adapters.py:142-144, 147-150).
    with patch(
        "app.application.tool_adapters.call_mcp_tool",
        new=AsyncMock(return_value=("plain failure", True)),
    ):
        result = await mcp.invoke(mcp_snapshot, {}, context)
    assert result.ok is False
    assert result.error_code == "mcp_tool_error"
    assert result.data == "plain failure"
    # MCP adapter client error, confirmed outcome (tool_adapters.py:130-140).
    with patch(
        "app.application.tool_adapters.call_mcp_tool",
        new=AsyncMock(side_effect=McpClientError("boom")),
    ):
        result = await mcp.invoke(mcp_snapshot, {}, context)
    assert result.ok is False
    assert result.error_code == "mcp_request_failed"
    assert result.outcome == "confirmed"
    # MCP adapter client error, uncertain outcome (tool_adapters.py:131, 138).
    uncertain_mcp = dataclasses.replace(mcp_snapshot, effect="external_write")
    with patch(
        "app.application.tool_adapters.call_mcp_tool",
        new=AsyncMock(side_effect=McpClientError("boom")),
    ):
        result = await mcp.invoke(uncertain_mcp, {}, context)
    assert result.ok is False
    assert result.error_code == "mcp_request_failed"
    assert result.outcome == "uncertain"


def test_workspace_creation_initializes_system_catalog() -> None:
    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        stranger_id, _stranger_token = create_active_user(
            client,
            admin_token,
            "tool-edge-stranger",
        )
        member_id, _member_token = create_active_user(
            client,
            admin_token,
            "tool-edge-member",
        )
        add_workspace_member(client, admin_token, workspace_id, member_id)
        run(assert_workspace_system_catalog(workspace_id))
        run(assert_tool_policy_revision_compare_and_swap(workspace_id))
        run(assert_mcp_discovery_materializes_first_leaf(workspace_id))
        run(assert_mcp_server_deletion_preserves_tool_history(workspace_id))
        run(assert_tool_runtime_is_durable(workspace_id))
        run(assert_python_tool_lifecycle(workspace_id))
        run(assert_tool_runtime_edge_branches(workspace_id, stranger_id))
        run(assert_mcp_source_management(workspace_id))
        run(assert_tool_management_branches(workspace_id, member_id))
        run(assert_workflow_tool_runtime(workspace_id))
        run(assert_tool_adapters(workspace_id))


def test_python_tool_http_lifecycle_and_private_grants() -> None:
    input_schema = {
        "type": "object",
        "properties": {"value": {"type": "string", "maxLength": 64}},
        "required": ["value"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {"value": {"type": "string", "maxLength": 64}},
        "required": ["value"],
        "additionalProperties": False,
    }
    definition = {
        "display_name": "Uppercase value",
        "description": "Uppercase one value.",
        "input_schema": input_schema,
        "output_schema": output_schema,
        "code": "result = {'value': inputs['value'].upper()}",
    }

    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        owner_id, owner_token = create_active_user(
            client,
            admin_token,
            "python-tool-owner",
        )
        viewer_id, viewer_token = create_active_user(
            client,
            admin_token,
            "python-tool-viewer",
        )
        stranger_id, stranger_token = create_active_user(
            client,
            admin_token,
            "python-tool-stranger",
        )
        draft_owner_id, draft_owner_token = create_active_user(
            client,
            admin_token,
            "python-draft-owner",
        )
        for user_id in (owner_id, viewer_id, stranger_id, draft_owner_id):
            add_workspace_member(client, admin_token, workspace_id, user_id)

        # A user who only belongs to a different workspace must not see this
        # workspace's tool catalog (404, not 403).
        cross_tenant_id, cross_tenant_token = create_active_user(
            client,
            admin_token,
            "python-tool-cross-tenant",
        )
        cross_workspace = client.post(
            "/api/v1/workspaces",
            headers=auth_headers(admin_token),
            json={
                "name": "Python Tool Cross Tenant",
                "admin_user_id": cross_tenant_id,
            },
        )
        assert cross_workspace.status_code == 201, cross_workspace.text

        tools_url = f"/api/v1/workspaces/{workspace_id}/tools"
        cross_tenant_catalog = client.get(
            tools_url,
            headers=auth_headers(cross_tenant_token),
        )
        assert cross_tenant_catalog.status_code == 404, cross_tenant_catalog.text
        draft_only = client.post(
            f"{tools_url}/python",
            headers=auth_headers(draft_owner_token),
            json={**definition, "display_name": "Draft only"},
        )
        assert draft_only.status_code == 201, draft_only.text
        retained_draft_owner = client.delete(
            f"/api/v1/admin/users/{draft_owner_id}",
            headers=auth_headers(admin_token),
        )
        assert retained_draft_owner.status_code == 409, retained_draft_owner.text

        created = client.post(
            f"{tools_url}/python",
            headers=auth_headers(owner_token),
            json=definition,
        )
        assert created.status_code == 201, created.text
        tool = created.json()
        tool_id = tool["id"]
        assert tool["kind"] == "python"
        assert tool["current_version_id"] is None
        assert tool["draft"]["revision"] == 1
        assert tool["draft"]["code"] == definition["code"]

        owner_catalog = client.get(tools_url, headers=auth_headers(owner_token))
        viewer_catalog = client.get(tools_url, headers=auth_headers(viewer_token))
        stranger_catalog = client.get(tools_url, headers=auth_headers(stranger_token))
        assert owner_catalog.status_code == 200, owner_catalog.text
        assert tool_id in {item["id"] for item in owner_catalog.json()}
        assert tool_id not in {item["id"] for item in viewer_catalog.json()}
        assert tool_id not in {item["id"] for item in stranger_catalog.json()}

        hidden = client.get(
            f"{tools_url}/{tool_id}",
            headers=auth_headers(viewer_token),
        )
        assert hidden.status_code == 404, hidden.text

        granted = client.put(
            f"{tools_url}/{tool_id}/permissions/{viewer_id}",
            headers=auth_headers(owner_token),
            json={"permission": "view"},
        )
        assert granted.status_code == 200, granted.text
        assert granted.json()["permission"] == "view"
        viewer_detail = client.get(
            f"{tools_url}/{tool_id}",
            headers=auth_headers(viewer_token),
        )
        assert viewer_detail.status_code == 200, viewer_detail.text
        assert viewer_detail.json()["can_view"] is True
        assert viewer_detail.json()["can_use"] is False
        assert viewer_detail.json()["draft"] is None
        assert "code" not in viewer_detail.text
        permissions = client.get(
            f"{tools_url}/{tool_id}/permissions",
            headers=auth_headers(owner_token),
        )
        assert permissions.status_code == 200, permissions.text
        assert [
            (item["user"]["id"], item["permission"])
            for item in permissions.json()
        ] == [(viewer_id, "view")]

        denied_test = client.post(
            f"{tools_url}/{tool_id}/tests",
            headers=auth_headers(viewer_token),
            json={"arguments": {"value": "nexa"}},
        )
        assert denied_test.status_code == 403, denied_test.text
        invalid_test = client.post(
            f"{tools_url}/{tool_id}/tests",
            headers=auth_headers(owner_token),
            json={"arguments": {}},
        )
        assert invalid_test.status_code == 422, invalid_test.text

        stale = client.put(
            f"{tools_url}/{tool_id}/draft",
            headers=auth_headers(owner_token),
            json={**definition, "expected_revision": 99},
        )
        assert stale.status_code == 409, stale.text
        updated = client.put(
            f"{tools_url}/{tool_id}/draft",
            headers=auth_headers(owner_token),
            json={
                **definition,
                "expected_revision": 1,
                "description": "Uppercase one value safely.",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 2

        from unittest.mock import AsyncMock, patch

        with patch(
            "app.application.tool_management.enqueue_tool_invocation",
            new_callable=AsyncMock,
        ) as dispatch:
            queued = client.post(
                f"{tools_url}/{tool_id}/tests",
                headers=auth_headers(owner_token),
                json={"arguments": {"value": "nexa"}},
            )
        assert queued.status_code == 202, queued.text
        invocation = queued.json()
        assert invocation["status"] == "queued"
        assert dispatch.await_count == 1
        assert dispatch.await_args.args[0] == invocation["id"]

        published = client.post(
            f"{tools_url}/{tool_id}/publish",
            headers=auth_headers(owner_token),
        )
        assert published.status_code == 200, published.text
        assert published.json()["current_version_id"]
        assert published.json()["approval"] == "auto"
        assert published.json()["effect"] == "pure"

        upgraded = client.put(
            f"{tools_url}/{tool_id}/permissions/{viewer_id}",
            headers=auth_headers(owner_token),
            json={"permission": "use"},
        )
        assert upgraded.status_code == 200, upgraded.text
        viewer_detail = client.get(
            f"{tools_url}/{tool_id}",
            headers=auth_headers(viewer_token),
        )
        assert viewer_detail.json()["can_use"] is True

        revoked = client.delete(
            f"{tools_url}/{tool_id}/permissions/{viewer_id}",
            headers=auth_headers(owner_token),
        )
        assert revoked.status_code == 204, revoked.text
        assert client.get(
            f"{tools_url}/{tool_id}",
            headers=auth_headers(viewer_token),
        ).status_code == 404

        disabled = client.post(
            f"{tools_url}/{tool_id}/disable",
            headers=auth_headers(owner_token),
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "disabled"
        enabled = client.post(
            f"{tools_url}/{tool_id}/enable",
            headers=auth_headers(owner_token),
        )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["status"] == "active"

        removed = client.delete(
            f"{tools_url}/{tool_id}",
            headers=auth_headers(owner_token),
        )
        assert removed.status_code == 204, removed.text
        assert client.get(
            f"{tools_url}/{tool_id}",
            headers=auth_headers(owner_token),
        ).status_code == 404
        archived_publish = client.post(
            f"{tools_url}/{tool_id}/publish",
            headers=auth_headers(owner_token),
        )
        assert archived_publish.status_code == 409, archived_publish.text


def test_canonical_mcp_policy_allows_owner_read_only_attestation() -> None:
    from unittest.mock import AsyncMock, patch

    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        owner_id, owner_token = create_active_user(
            client,
            admin_token,
            "mcp-policy-owner",
        )
        add_workspace_member(client, admin_token, workspace_id, owner_id)
        discovery = SimpleNamespace(
            tools=[
                {
                    "name": "lookup",
                    "description": "Lookup a record.",
                    "input_schema": {
                        "type": "object",
                        "additionalProperties": False,
                    },
                }
            ]
        )
        source_url = f"/api/v1/workspaces/{workspace_id}/tool-sources"
        with patch(
            "app.shareddomain.tools.services.discover_mcp_tools",
            new=AsyncMock(return_value=discovery),
        ):
            created = client.post(
                f"{source_url}/mcp",
                headers=auth_headers(owner_token),
                json={
                    "name": "Owner MCP",
                    "transport": "streamable_http",
                    "url": "https://tools.example.com/mcp",
                },
            )
        assert created.status_code == 201, created.text
        source = created.json()
        assert source["kind"] == "mcp"
        listed_sources = client.get(
            source_url,
            headers=auth_headers(owner_token),
        )
        assert listed_sources.status_code == 200, listed_sources.text
        assert [item["id"] for item in listed_sources.json()] == [source["id"]]

        tools = client.get(
            f"/api/v1/workspaces/{workspace_id}/tools",
            headers=auth_headers(owner_token),
        )
        assert tools.status_code == 200, tools.text
        tool = next(item for item in tools.json() if item["kind"] == "mcp")

        response = client.put(
            f"/api/v1/workspaces/{workspace_id}/tools/{tool['id']}/policy",
            headers=auth_headers(owner_token),
            json={"mode": "read_only"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["id"] == tool["id"]
        assert payload["approval"] == "auto"
        assert payload["effect"] == "external_read"
        assert payload["workflow_callable"] is True

        with patch(
            "app.shareddomain.tools.services.discover_mcp_tools",
            new=AsyncMock(return_value=discovery),
        ):
            refreshed = client.post(
                f"{source_url}/{source['id']}/refresh",
                headers=auth_headers(owner_token),
            )
        assert refreshed.status_code == 200, refreshed.text
        disabled = client.post(
            f"{source_url}/{source['id']}/disable",
            headers=auth_headers(owner_token),
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "disabled"
        enabled = client.post(
            f"{source_url}/{source['id']}/enable",
            headers=auth_headers(owner_token),
        )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["status"] == "active"
        deleted = client.delete(
            f"{source_url}/{source['id']}",
            headers=auth_headers(owner_token),
        )
        assert deleted.status_code == 204, deleted.text


def test_tool_tasks_never_execute_inline_and_recover_queued_tests() -> None:
    from app.application.tool_runtime import ToolInvocationBusy
    from app.infrastructure import tool_dispatch
    from app.tasks import tools as tool_tasks
    from tests.support import settings as test_settings

    original_configure = tool_tasks.configure_task_worker
    original_execute = tool_tasks.execute_tool_invocation
    original_recover = tool_tasks.list_recoverable_tool_test_invocation_ids
    original_apply_async = tool_tasks.run_tool_invocation_job.apply_async
    original_send_task = tool_dispatch.celery_app.send_task
    original_log_error = tool_dispatch.log_error
    original_broker_url = tool_dispatch.celery_app.conf.broker_url
    original_eager = tool_dispatch.celery_app.conf.task_always_eager
    try:
        tool_tasks.configure_task_worker = lambda _settings: None
        tool_dispatch.log_error = lambda *args, **kwargs: None
        calls: list[tuple[str, str]] = []

        async def execute(invocation_id, _settings, worker_task_id):
            calls.append((invocation_id, worker_task_id))

        tool_tasks.execute_tool_invocation = execute
        real_task = tool_tasks.run_tool_invocation_job._get_current_object()
        run_body = type(real_task).run
        run_body(
            SimpleNamespace(
                request=SimpleNamespace(id="tool-worker-1"),
                retry=lambda **_kwargs: None,
            ),
            "invocation-1",
        )
        assert calls == [("invocation-1", "tool-worker-1")]

        async def busy(*_args, **_kwargs):
            raise ToolInvocationBusy("busy")

        retry_kwargs: dict = {}

        class RetrySignal(Exception):
            pass

        def retry(**kwargs):
            retry_kwargs.update(kwargs)
            return RetrySignal()

        tool_tasks.execute_tool_invocation = busy
        try:
            run_body(
                SimpleNamespace(
                    request=SimpleNamespace(id="tool-worker-2"),
                    retry=retry,
                ),
                "invocation-2",
            )
        except RetrySignal as exc:
            assert retry_kwargs["countdown"] == 30
            assert isinstance(exc.__cause__, ToolInvocationBusy)
        else:
            raise AssertionError("A busy Tool invocation must be retried.")

        async def recoverable():
            return ["invocation-3", "invocation-4"]

        dispatched: list[dict] = []
        tool_tasks.list_recoverable_tool_test_invocation_ids = recoverable
        tool_tasks.run_tool_invocation_job.apply_async = lambda **kwargs: dispatched.append(
            kwargs
        )
        tool_tasks.recover_tool_invocations_job()
        assert dispatched == [
            {"args": ("invocation-3",)},
            {"args": ("invocation-4",)},
        ]

        dispatched.clear()
        tool_dispatch.celery_app.conf.task_always_eager = True
        tool_dispatch.celery_app.send_task = lambda *args, **kwargs: dispatched.append(
            {"task": args[0], **kwargs}
        )
        asyncio.run(
            tool_dispatch.enqueue_tool_invocation("invocation-5", test_settings())
        )
        assert dispatched == [
            {"task": "app.tools.run", "args": ("invocation-5",)}
        ]
        assert tool_dispatch.celery_app.conf.task_always_eager is True
        assert calls == [("invocation-1", "tool-worker-1")]

        def unavailable(**_kwargs):
            raise OSError("broker unavailable")

        tool_dispatch.celery_app.send_task = unavailable
        asyncio.run(
            tool_dispatch.enqueue_tool_invocation("invocation-6", test_settings())
        )
    finally:
        tool_tasks.configure_task_worker = original_configure
        tool_tasks.execute_tool_invocation = original_execute
        tool_tasks.list_recoverable_tool_test_invocation_ids = original_recover
        tool_tasks.run_tool_invocation_job.apply_async = original_apply_async
        tool_dispatch.celery_app.send_task = original_send_task
        tool_dispatch.log_error = original_log_error
        tool_dispatch.celery_app.conf.broker_url = original_broker_url
        tool_dispatch.celery_app.conf.task_always_eager = original_eager


def test_tool_boundaries_reject_unsafe_payloads() -> None:
    from app.entities.tools import MAX_TOOL_SCHEMA_DEPTH, validate_tool_json_schema
    from app.shareddomain.tools.runtime import (
        build_tool_snapshot,
        validate_tool_arguments,
    )

    # SEC-010: prototype-pollution keys, over-deep JSON, NaN/Infinity and
    # non-string keys are rejected at the schema/JSON boundaries.

    def expect_schema_error(schema: dict, fragment: str) -> None:
        try:
            validate_tool_json_schema(schema)
        except ValueError as exc:
            assert fragment in str(exc), (fragment, str(exc))
        else:
            raise AssertionError(f"schema accepted: {schema!r}")

    expect_schema_error(
        {
            "type": "object",
            "properties": {"v": {"type": "number", "const": float("nan")}},
        },
        "must be JSON serializable",
    )
    expect_schema_error(
        {"type": "object", "$ref": "#/definitions/x", "additionalProperties": False},
        "cannot contain references",
    )
    expect_schema_error(
        {"type": "object", "properties": {}, "additionalProperties": True},
        "cannot allow additional properties",
    )
    expect_schema_error(
        {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
            "allOf": [],
        },
        "unsupported keyword",
    )
    deep_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    node = deep_schema
    for _ in range(MAX_TOOL_SCHEMA_DEPTH + 2):
        child = {"type": "object", "properties": {}, "additionalProperties": False}
        node["properties"] = {"nested": child}
        node = child
    expect_schema_error(deep_schema, "too deeply nested")

    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)

        async def run() -> None:
            from app.infrastructure.repositories import tools as tool_repository
            from app.infrastructure.repositories import user as user_repository

            async with get_session_factory()() as db:
                actor = await user_repository.get_active_user_by_username(
                    db, "admin"
                )
                assert actor is not None
                tool = next(
                    item
                    for item in await tool_repository.list_tools(
                        db, workspace_id
                    )
                    if item.stable_key == "current_time"
                )
                source = await tool_repository.get_tool_source(
                    db, workspace_id, tool.source_id
                )
                version = await tool_repository.get_tool_version(
                    db, workspace_id, tool.current_version_id or ""
                )
                policy = await tool_repository.get_tool_policy(
                    db, workspace_id, tool.id
                )
                assert (
                    source is not None and version is not None and policy is not None
                )
                snapshot = build_tool_snapshot(
                    tool, source, version, policy, actor.id
                )

                def expect_arguments_error(arguments: object, fragment: str) -> None:
                    try:
                        validate_tool_arguments(snapshot, arguments)
                    except ValueError as exc:
                        assert fragment in str(exc), (fragment, str(exc))
                    else:
                        raise AssertionError(
                            f"arguments accepted: {arguments!r}"
                        )

                # NaN / Infinity are not valid JSON.
                expect_arguments_error(
                    {"format": float("nan")}, "must be valid JSON"
                )
                expect_arguments_error(
                    {"format": float("inf")}, "must be valid JSON"
                )
                # Prototype-pollution and non-string keys fail the closed schema.
                expect_arguments_error(
                    {"__proto__": "polluted"}, "Tool arguments are invalid"
                )
                expect_arguments_error(
                    {"constructor": "polluted"}, "Tool arguments are invalid"
                )
                expect_arguments_error({1: "value"}, "Tool arguments are invalid")
                # Over-deep JSON fails the closed schema at the top level.
                expect_arguments_error(
                    {"a": {"b": {"c": {"d": {"e": 1}}}}},
                    "Tool arguments are invalid",
                )

        asyncio.run(run())


def test_tool_tasks_are_registered() -> None:
    from app.infrastructure.celery import celery_app
    from app.tasks.maintenance import cleanup_expired_generated_artifacts_job

    assert "app.tools.run" in celery_app.tasks
    assert "app.tools.recover" in celery_app.tasks
    assert cleanup_expired_generated_artifacts_job.name in celery_app.tasks
    assert (
        celery_app.conf.beat_schedule["recover-frequent-maintenance"]["task"]
        == "app.maintenance.recover_frequent"
    )


def main() -> None:
    test_stable_catalog_contract_matches_legacy_mcp_identity()
    test_agent_publication_migration_supports_sqlite_foreign_keys()
    test_mcp_network_policy_migration_is_reversible_and_defaults_legacy()
    test_legacy_disabled_tools_remain_disabled_after_backfill()
    test_mcp_function_name_candidates_extend_stable_digest_on_collision()
    test_resolved_mcp_tool_preserves_catalog_function_name()
    test_disabled_mcp_policy_wins_over_definition_drift()
    test_mcp_hash_matches_legacy_annotation_normalization()
    test_migration_collects_policy_only_tools_deterministically()
    test_migration_grants_tools_only_to_regular_members()
    test_agent_publication_backfill_does_not_restore_membership_revoked_use()
    test_entities_and_orm_columns_match_exactly()
    test_orm_enforces_tenant_scoped_relations_and_legal_states()
    test_tool_versions_are_immutable_at_repository_boundary()
    test_migration_reference_scanner_keeps_historical_mcp_tuples()
    test_private_catalog_filters_before_pagination_for_every_role()
    test_private_tool_permission_lifecycle_preserves_bindings()
    test_mcp_resolution_requires_current_binding_owner_use_permission()
    test_mcp_resolution_rejects_missing_authorization_context()
    test_workspace_creation_initializes_system_catalog()
    test_generated_artifact_link_serves_static_html()
    test_python_tool_http_lifecycle_and_private_grants()
    test_canonical_mcp_policy_allows_owner_read_only_attestation()
    test_tool_tasks_never_execute_inline_and_recover_queued_tests()
    test_tool_tasks_are_registered()
    test_tool_boundaries_reject_unsafe_payloads()
    print("TOOLS_SUITE_OK")


if __name__ == "__main__":
    main()
