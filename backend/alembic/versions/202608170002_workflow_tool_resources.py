"""Persist immutable Workflow Tool resource snapshots.

Revision ID: 202608170002
Revises: 202608170001
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "202608170002"
down_revision: str | None = "202608170001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_NAMESPACE = UUID("2df58f89-2f5c-4e2b-9545-d50fb806a6db")
_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def _stable_catalog_id(key: str) -> str:
    return str(uuid5(_CATALOG_NAMESPACE, key))


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _legacy_snapshot() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "legacy": True,
        "knowledge_base_ids": [],
        "tools": [],
        "agents": [],
    }


def _assert_workflow_runs_drained(bind: sa.Connection) -> None:
    runs = sa.table(
        "agent_runs",
        sa.column("id", sa.String(36)),
        sa.column("status", sa.String(20)),
    )
    details = sa.table("workflow_run_details", sa.column("run_id", sa.String(36)))
    active_run_id = bind.execute(
        sa.select(runs.c.id)
        .select_from(runs.join(details, runs.c.id == details.c.run_id))
        .where(runs.c.status.not_in(_TERMINAL_STATUSES))
        .limit(1)
    ).scalar_one_or_none()
    if active_run_id is not None:
        raise RuntimeError(
            "Workflow Runs must be drained before enabling canonical Tool execution."
        )


def _inline_python_rows(
    workspace_id: str,
    timestamp: datetime,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_id = _stable_catalog_id(f"source:{workspace_id}:builtin")
    tool_id = _stable_catalog_id(f"tool:{workspace_id}:builtin:inline_python")
    input_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "maxLength": 8192},
            "inputs": {"type": "object"},
        },
        "required": ["code", "inputs"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {"result": {}},
        "required": ["result"],
        "additionalProperties": False,
    }
    execution_spec = {
        "builtin": "inline_python",
        "workflow_only": True,
        "direct_only": True,
    }
    definition_hash = _canonical_hash(
        {
            "name": "inline_python",
            "description": "Run inline Python in the Workflow sandbox.",
            "input_schema": input_schema,
            "output_schema": output_schema,
            "execution_spec": execution_spec,
        }
    )
    version_id = _stable_catalog_id(f"version:{tool_id}:{definition_hash}")
    return (
        {
            "id": source_id,
            "workspace_id": workspace_id,
            "mcp_server_id": None,
            "kind": "builtin",
            "name": "Built-in",
            "status": "active",
            "created_by_user_id": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        {
            "id": tool_id,
            "workspace_id": workspace_id,
            "source_id": source_id,
            "kind": "builtin",
            "stable_key": "inline_python",
            "function_name": "inline_python",
            "current_version_id": None,
            "status": "active",
            "availability": "available",
            "created_by_user_id": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        {
            "id": version_id,
            "workspace_id": workspace_id,
            "tool_id": tool_id,
            "revision": 1,
            "display_name": "Python code",
            "description": "Run inline Python in the Workflow sandbox.",
            "input_schema": input_schema,
            "output_schema": output_schema,
            "execution_spec": execution_spec,
            "definition_hash": definition_hash,
            "created_by_user_id": None,
            "created_at": timestamp,
        },
        {
            "id": _stable_catalog_id(f"policy:{tool_id}"),
            "workspace_id": workspace_id,
            "tool_id": tool_id,
            "tool_version_id": version_id,
            "definition_hash": definition_hash,
            "revision": 1,
            "approval": "auto",
            "effect": "pure",
            "allowed_access_sources": ["console", "public", "api"],
            "workflow_callable": True,
            "parallel_safe": False,
            "reviewed_by_user_id": None,
            "reviewed_at": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )


def _backfill_inline_python(bind: sa.Connection) -> None:
    workspaces = sa.table("workspaces", sa.column("id", sa.String(36)))
    sources = sa.table(
        "tool_sources",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("mcp_server_id", sa.String(36)),
        sa.column("kind", sa.String(20)),
        sa.column("name", sa.String(120)),
        sa.column("status", sa.String(20)),
        sa.column("created_by_user_id", sa.String(36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    tools = sa.table(
        "tools",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("source_id", sa.String(36)),
        sa.column("kind", sa.String(20)),
        sa.column("stable_key", sa.String(255)),
        sa.column("function_name", sa.String(255)),
        sa.column("current_version_id", sa.String(36)),
        sa.column("status", sa.String(20)),
        sa.column("availability", sa.String(20)),
        sa.column("created_by_user_id", sa.String(36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    versions = sa.table(
        "tool_versions",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("revision", sa.Integer()),
        sa.column("display_name", sa.String(120)),
        sa.column("description", sa.Text()),
        sa.column("input_schema", sa.JSON()),
        sa.column("output_schema", sa.JSON()),
        sa.column("execution_spec", sa.JSON()),
        sa.column("definition_hash", sa.String(64)),
        sa.column("created_by_user_id", sa.String(36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    policies = sa.table(
        "tool_policies",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("tool_version_id", sa.String(36)),
        sa.column("definition_hash", sa.String(64)),
        sa.column("revision", sa.Integer()),
        sa.column("approval", sa.String(20)),
        sa.column("effect", sa.String(30)),
        sa.column("allowed_access_sources", sa.JSON()),
        sa.column("workflow_callable", sa.Boolean()),
        sa.column("parallel_safe", sa.Boolean()),
        sa.column("reviewed_by_user_id", sa.String(36)),
        sa.column("reviewed_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    timestamp = datetime.now(UTC)
    for workspace_id in bind.execute(sa.select(workspaces.c.id)).scalars():
        source, tool, version, policy = _inline_python_rows(workspace_id, timestamp)
        if bind.execute(
            sa.select(sources.c.id).where(sources.c.id == source["id"])
        ).scalar_one_or_none() is None:
            bind.execute(sources.insert().values(**source))
        existing_tool_id = bind.execute(
            sa.select(tools.c.id).where(tools.c.id == tool["id"])
        ).scalar_one_or_none()
        if existing_tool_id is None:
            occupied = bind.execute(
                sa.select(tools.c.id).where(
                    tools.c.workspace_id == workspace_id,
                    tools.c.function_name == tool["function_name"],
                )
            ).scalar_one_or_none()
            if occupied is not None:
                tool["function_name"] = (
                    f"inline_python_{tool['id'].replace('-', '')[:12]}"
                )
            bind.execute(tools.insert().values(**tool))
        if bind.execute(
            sa.select(versions.c.id).where(versions.c.id == version["id"])
        ).scalar_one_or_none() is None:
            bind.execute(versions.insert().values(**version))
        if bind.execute(
            sa.select(policies.c.id).where(policies.c.id == policy["id"])
        ).scalar_one_or_none() is None:
            bind.execute(policies.insert().values(**policy))
        bind.execute(
            tools.update()
            .where(tools.c.id == tool["id"])
            .values(current_version_id=version["id"])
        )


def _backfill_inline_python_bindings(bind: sa.Connection) -> None:
    definitions = sa.table(
        "workflow_definitions",
        sa.column("workspace_id", sa.String(36)),
        sa.column("agent_id", sa.String(36)),
        sa.column("graph", sa.JSON()),
        sa.column("updated_by_user_id", sa.String(36)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    tools = sa.table(
        "tools",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("kind", sa.String(20)),
        sa.column("stable_key", sa.String(255)),
        sa.column("current_version_id", sa.String(36)),
    )
    bindings = sa.table(
        "application_tool_bindings",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("application_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("tool_version_id", sa.String(36)),
        sa.column("bound_by_user_id", sa.String(36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    inline_tools = {
        row["workspace_id"]: row
        for row in bind.execute(
            sa.select(tools).where(
                tools.c.kind == "builtin",
                tools.c.stable_key == "inline_python",
            )
        ).mappings()
    }
    existing = {
        (row["workspace_id"], row["application_id"], row["tool_id"])
        for row in bind.execute(
            sa.select(
                bindings.c.workspace_id,
                bindings.c.application_id,
                bindings.c.tool_id,
            )
        ).mappings()
    }
    rows: list[dict[str, Any]] = []
    for definition in bind.execute(sa.select(definitions)).mappings():
        try:
            _knowledge, _mcp, _canonical, has_code = _graph_references(
                definition["graph"]
            )
        except ValueError:
            continue
        if not has_code:
            continue
        tool = inline_tools.get(definition["workspace_id"])
        if tool is None or tool["current_version_id"] is None:
            raise RuntimeError("Inline Python Tool could not be bound to a Workflow.")
        key = (definition["workspace_id"], definition["agent_id"], tool["id"])
        if key in existing:
            continue
        rows.append(
            {
                "id": _stable_catalog_id(
                    f"binding:{definition['agent_id']}:{tool['id']}"
                ),
                "workspace_id": definition["workspace_id"],
                "application_id": definition["agent_id"],
                "tool_id": tool["id"],
                "tool_version_id": tool["current_version_id"],
                "bound_by_user_id": definition["updated_by_user_id"],
                "created_at": definition["updated_at"] or datetime.now(UTC),
            }
        )
        existing.add(key)
    if rows:
        bind.execute(bindings.insert(), rows)


def _graph_references(
    graph: Any,
) -> tuple[list[str], list[tuple[str, str]], list[tuple[str, str]], bool]:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        raise ValueError("Workflow graph is invalid.")
    knowledge: list[str] = []
    mcp: list[tuple[str, str]] = []
    canonical: list[tuple[str, str]] = []
    has_code = False
    for node in graph["nodes"]:
        if not isinstance(node, dict):
            raise ValueError("Workflow graph is invalid.")
        data = node.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("config"), dict):
            continue
        node_type = data.get("type")
        config = data["config"]
        if node_type == "knowledge":
            values = config.get("knowledge_base_ids")
            if isinstance(values, list):
                knowledge.extend(item for item in values if isinstance(item, str))
            single = config.get("knowledge_base_id")
            if isinstance(single, str):
                knowledge.append(single)
        elif node_type == "mcp":
            server_id = config.get("server_id")
            tool_name = config.get("tool_name")
            if isinstance(server_id, str) and isinstance(tool_name, str):
                mcp.append((server_id, tool_name))
        elif node_type == "code":
            has_code = True
        elif node_type == "tool":
            reference = config.get("tool")
            if isinstance(reference, dict):
                tool_id = reference.get("tool_id")
                version_id = reference.get("version_id")
                if isinstance(tool_id, str) and isinstance(version_id, str):
                    canonical.append((tool_id, version_id))
        elif node_type == "llm":
            if config.get("mcp_enable") is True:
                for item in config.get("mcp_servers") or []:
                    if not isinstance(item, dict):
                        continue
                    server_id = item.get("server_id")
                    tool_name = item.get("tool_name")
                    if isinstance(server_id, str) and isinstance(tool_name, str):
                        mcp.append((server_id, tool_name))
            for item in config.get("tools") or []:
                if not isinstance(item, dict):
                    continue
                tool_id = item.get("tool_id")
                version_id = item.get("version_id")
                if isinstance(tool_id, str) and isinstance(version_id, str):
                    canonical.append((tool_id, version_id))
    return (
        list(dict.fromkeys(knowledge)),
        list(dict.fromkeys(mcp)),
        list(dict.fromkeys(canonical)),
        has_code,
    )


def _graph_has_canonical_tool_reference(graph: Any) -> bool:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return False
    for node in graph["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
            continue
        data = node["data"]
        if data.get("type") == "tool":
            return True
        config = data.get("config")
        if (
            data.get("type") == "llm"
            and isinstance(config, dict)
            and isinstance(config.get("tools"), list)
            and bool(config["tools"])
        ):
            return True
    return False


def _tool_snapshot(
    tool: Mapping[str, Any],
    source: Mapping[str, Any],
    version: Mapping[str, Any],
    policy: Mapping[str, Any],
    binder_id: str,
) -> dict[str, Any]:
    if (
        policy["tool_version_id"] != version["id"]
        or policy["definition_hash"] != version["definition_hash"]
        or policy["approval"] != "auto"
        or policy["workflow_callable"] is not True
    ):
        raise ValueError("Workflow Tool policy is not executable.")
    return {
        "schema_version": 1,
        "tool_id": tool["id"],
        "version_id": version["id"],
        "source_id": source["id"],
        "kind": tool["kind"],
        "function_name": tool["function_name"],
        "display_name": version["display_name"],
        "description": version["description"],
        "input_schema": version["input_schema"],
        "output_schema": version["output_schema"],
        "definition_hash": version["definition_hash"],
        "policy_id": policy["id"],
        "policy_revision": policy["revision"],
        "bound_by_user_id": binder_id,
        "approval": policy["approval"],
        "effect": policy["effect"],
        "allowed_access_sources": policy["allowed_access_sources"],
        "workflow_callable": policy["workflow_callable"],
        "parallel_safe": policy["parallel_safe"],
        "execution_spec": version["execution_spec"],
    }


def _backfill_workflow_versions(bind: sa.Connection) -> None:
    workflow_versions = sa.table(
        "workflow_versions",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("agent_id", sa.String(36)),
        sa.column("graph", sa.JSON()),
        sa.column("published_by_user_id", sa.String(36)),
        sa.column("resource_snapshot", sa.JSON()),
        sa.column("resource_hash", sa.String(64)),
    )
    sources_table = sa.table(
        "tool_sources",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("mcp_server_id", sa.String(36)),
    )
    tools_table = sa.table(
        "tools",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("source_id", sa.String(36)),
        sa.column("kind", sa.String(20)),
        sa.column("stable_key", sa.String(255)),
        sa.column("function_name", sa.String(255)),
        sa.column("current_version_id", sa.String(36)),
    )
    tool_versions_table = sa.table(
        "tool_versions",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("display_name", sa.String(120)),
        sa.column("description", sa.Text()),
        sa.column("input_schema", sa.JSON()),
        sa.column("output_schema", sa.JSON()),
        sa.column("execution_spec", sa.JSON()),
        sa.column("definition_hash", sa.String(64)),
    )
    policies_table = sa.table(
        "tool_policies",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("tool_version_id", sa.String(36)),
        sa.column("definition_hash", sa.String(64)),
        sa.column("revision", sa.Integer()),
        sa.column("approval", sa.String(20)),
        sa.column("effect", sa.String(30)),
        sa.column("allowed_access_sources", sa.JSON()),
        sa.column("workflow_callable", sa.Boolean()),
        sa.column("parallel_safe", sa.Boolean()),
    )
    bindings_table = sa.table(
        "application_tool_bindings",
        sa.column("workspace_id", sa.String(36)),
        sa.column("application_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("tool_version_id", sa.String(36)),
        sa.column("bound_by_user_id", sa.String(36)),
    )

    sources = {
        row["id"]: row for row in bind.execute(sa.select(sources_table)).mappings()
    }
    tools = {
        (row["workspace_id"], row["id"]): row
        for row in bind.execute(sa.select(tools_table)).mappings()
    }
    tool_versions = {
        (row["workspace_id"], row["id"]): row
        for row in bind.execute(sa.select(tool_versions_table)).mappings()
    }
    policies = {
        (row["workspace_id"], row["tool_id"]): row
        for row in bind.execute(sa.select(policies_table)).mappings()
    }
    bindings = {
        (row["workspace_id"], row["application_id"], row["tool_id"]): row
        for row in bind.execute(sa.select(bindings_table)).mappings()
    }
    mcp_tools = {
        (tool["workspace_id"], source["mcp_server_id"], tool["stable_key"]): tool
        for tool in tools.values()
        if (source := sources.get(tool["source_id"])) is not None
        and source["mcp_server_id"] is not None
    }
    inline_tools = {
        workspace_id: tool
        for (workspace_id, _tool_id), tool in tools.items()
        if tool["kind"] == "builtin" and tool["stable_key"] == "inline_python"
    }

    legacy = _legacy_snapshot()
    for row in bind.execute(sa.select(workflow_versions)).mappings():
        try:
            knowledge, legacy_mcp, canonical, has_code = _graph_references(row["graph"])
            references: list[tuple[Mapping[str, Any], str, str]] = []
            for server_id, tool_name in legacy_mcp:
                tool = mcp_tools[(row["workspace_id"], server_id, tool_name)]
                binding = bindings.get(
                    (row["workspace_id"], row["agent_id"], tool["id"])
                )
                references.append(
                    (
                        tool,
                        binding["tool_version_id"]
                        if binding is not None
                        else tool["current_version_id"],
                        binding["bound_by_user_id"]
                        if binding is not None
                        else row["published_by_user_id"],
                    )
                )
            for tool_id, version_id in canonical:
                tool = tools[(row["workspace_id"], tool_id)]
                binding = bindings.get(
                    (row["workspace_id"], row["agent_id"], tool_id)
                )
                references.append(
                    (
                        tool,
                        version_id,
                        binding["bound_by_user_id"]
                        if binding is not None
                        else row["published_by_user_id"],
                    )
                )
            if has_code:
                inline = inline_tools[row["workspace_id"]]
                references.append(
                    (
                        inline,
                        inline["current_version_id"],
                        row["published_by_user_id"],
                    )
                )

            snapshots_by_tool: dict[str, dict[str, Any]] = {}
            for tool, version_id, binder_id in references:
                version = tool_versions[(row["workspace_id"], version_id)]
                policy = policies[(row["workspace_id"], tool["id"])]
                source = sources[tool["source_id"]]
                snapshot = _tool_snapshot(tool, source, version, policy, binder_id)
                existing = snapshots_by_tool.setdefault(tool["id"], snapshot)
                if existing["version_id"] != snapshot["version_id"]:
                    raise ValueError("Workflow references multiple Tool versions.")
            resource = {
                "schema_version": 1,
                "migration_legacy": True,
                "knowledge_base_ids": sorted(set(knowledge)),
                "tools": sorted(
                    snapshots_by_tool.values(),
                    key=lambda item: (item["tool_id"], item["version_id"]),
                ),
                "agents": [],
            }
        except (KeyError, TypeError, ValueError) as exc:
            if _graph_has_canonical_tool_reference(row["graph"]):
                raise RuntimeError(
                    "Canonical Workflow Tool references could not be migrated."
                ) from exc
            resource = legacy
        bind.execute(
            workflow_versions.update()
            .where(workflow_versions.c.id == row["id"])
            .values(
                resource_snapshot=resource,
                resource_hash=_canonical_hash(resource),
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE workflow_versions, workflow_run_details, agent_runs "
                "IN ACCESS EXCLUSIVE MODE"
            )
        )
    _assert_workflow_runs_drained(bind)
    op.add_column(
        "workflow_versions",
        sa.Column("resource_snapshot", sa.JSON(), nullable=True),
    )
    op.add_column(
        "workflow_versions",
        sa.Column("resource_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "workflow_run_details",
        sa.Column("resource_snapshot", sa.JSON(), nullable=True),
    )
    op.add_column(
        "workflow_run_details",
        sa.Column("resource_hash", sa.String(length=64), nullable=True),
    )
    _backfill_inline_python(bind)
    _backfill_inline_python_bindings(bind)
    _backfill_workflow_versions(bind)
    legacy = _legacy_snapshot()
    details = sa.table(
        "workflow_run_details",
        sa.column("resource_snapshot", sa.JSON()),
        sa.column("resource_hash", sa.String(64)),
    )
    bind.execute(
        details.update().values(
            resource_snapshot=legacy,
            resource_hash=_canonical_hash(legacy),
        )
    )
    with op.batch_alter_table("workflow_versions") as batch:
        batch.alter_column("resource_snapshot", nullable=False)
        batch.alter_column("resource_hash", nullable=False)
    with op.batch_alter_table("workflow_run_details") as batch:
        batch.alter_column("resource_snapshot", nullable=False)
        batch.alter_column("resource_hash", nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE workflow_versions, workflow_run_details, agent_runs "
                "IN ACCESS EXCLUSIVE MODE"
            )
        )
    _assert_workflow_runs_drained(bind)
    definitions = sa.table(
        "workflow_definitions",
        sa.column("id", sa.String(36)),
        sa.column("graph", sa.JSON()),
    )
    for row in bind.execute(sa.select(definitions)).mappings():
        try:
            _knowledge, _mcp, canonical, _has_code = _graph_references(row["graph"])
        except ValueError as exc:
            raise RuntimeError("Workflow draft graph is invalid.") from exc
        if canonical:
            raise RuntimeError(
                "Canonical Workflow drafts exist; downgrade would lose execution semantics."
            )
    for table_name in ("workflow_versions", "workflow_run_details"):
        table = sa.table(
            table_name,
            sa.column("id", sa.String(36)),
            sa.column("resource_snapshot", sa.JSON()),
        )
        for row in bind.execute(sa.select(table)).mappings():
            snapshot = row["resource_snapshot"]
            if not isinstance(snapshot, dict) or not (
                snapshot.get("legacy") is True
                or snapshot.get("migration_legacy") is True
            ):
                raise RuntimeError(
                    "Canonical Workflow snapshots exist; downgrade would lose execution semantics."
                )
    with op.batch_alter_table("workflow_run_details") as batch:
        batch.drop_column("resource_hash")
        batch.drop_column("resource_snapshot")
    with op.batch_alter_table("workflow_versions") as batch:
        batch.drop_column("resource_hash")
        batch.drop_column("resource_snapshot")
