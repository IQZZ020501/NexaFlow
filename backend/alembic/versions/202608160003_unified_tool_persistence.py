"""Add unified Tool persistence and backfill legacy MCP references."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op


revision: str = "202608160003"
down_revision: str | None = "202608160002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CATALOG_ID_NAMESPACE = UUID("2df58f89-2f5c-4e2b-9545-d50fb806a6db")


def _stable_catalog_id(key: str) -> str:
    return str(uuid5(_CATALOG_ID_NAMESPACE, key))


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mcp_input_schema(definition: Mapping[str, Any]) -> Any:
    return (
        definition.get("input_schema")
        or definition.get("inputSchema")
        or {"type": "object"}
    )


def _mcp_annotation_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if type(value) in (int, float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.lower()
        if normalized in {"1", "on", "t", "true", "y", "yes"}:
            return True
        if normalized in {"0", "off", "f", "false", "n", "no"}:
            return False
    raise ValueError("Invalid MCP ToolAnnotations boolean value.")


def _normalize_mcp_annotations(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("MCP Tool annotations must be an object.")

    normalized: dict[str, Any] = {}
    title = value.get("title")
    if title is not None:
        if not isinstance(title, str):
            raise ValueError("MCP Tool annotation title must be a string.")
        normalized["title"] = title
    for field_name, alias in (
        ("read_only_hint", "readOnlyHint"),
        ("destructive_hint", "destructiveHint"),
        ("idempotent_hint", "idempotentHint"),
        ("open_world_hint", "openWorldHint"),
    ):
        if alias in value:
            field_value = value[alias]
        elif field_name in value:
            field_value = value[field_name]
        else:
            continue
        if field_value is not None:
            normalized[alias] = _mcp_annotation_bool(field_value)
    return normalized


def _mcp_definition_hash(definition: dict[str, Any]) -> str:
    return _canonical_hash(
        {
            "name": str(definition.get("name") or ""),
            "description": str(definition.get("description") or ""),
            "input_schema": _mcp_input_schema(definition),
            "annotations": _normalize_mcp_annotations(
                definition.get("annotations")
            ),
        }
    )


def _mcp_function_name(server_id: str, tool_name: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_name).strip("_")[:40] or "tool"
    digest = hashlib.sha256(f"{server_id}:{tool_name}".encode()).hexdigest()[:8]
    return f"mcp_{stem}_{digest}"


def _extract_mcp_references(value: Any) -> set[tuple[str, str]]:
    references: set[tuple[str, str]] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str):
            try:
                visit(json.loads(item))
            except (TypeError, ValueError):
                return
        elif isinstance(item, dict):
            server_id = item.get("server_id")
            tool_name = item.get("tool_name")
            if (
                isinstance(server_id, str)
                and server_id
                and isinstance(tool_name, str)
                and tool_name
            ):
                references.add((server_id, tool_name))
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return references


def _add_reference(
    references: dict[tuple[str, str, str], str | None],
    workspace_id: str,
    server_id: str,
    tool_name: str,
    owner_id: str | None,
) -> None:
    key = (workspace_id, server_id, tool_name)
    existing_owner = references.get(key)
    if key not in references or (
        owner_id is not None
        and (existing_owner is None or owner_id < existing_owner)
    ):
        references[key] = owner_id


def _add_legacy_policy_references(
    references: dict[tuple[str, str, str], str | None],
    policies: Sequence[Mapping[str, Any]],
    servers: Mapping[tuple[str, str], Mapping[str, Any]],
) -> None:
    for policy in policies:
        workspace_id = policy["workspace_id"]
        server_id = policy["mcp_server_id"]
        server = servers.get((workspace_id, server_id))
        _add_reference(
            references,
            workspace_id,
            server_id,
            policy["tool_name"],
            server["created_by_user_id"] if server is not None else None,
        )


def _mcp_tool_available(
    definition: Mapping[str, Any] | None,
    server: Mapping[str, Any] | None,
) -> bool:
    return (
        definition is not None
        and server is not None
        and server["status"] == "active"
    )


def _should_backfill_use_grant(
    *,
    bound_by_user_id: str,
    tool_owner_id: str | None,
    workspace_role: str | None,
    is_global_admin: bool,
    grant_exists: bool,
) -> bool:
    return (
        bound_by_user_id != tool_owner_id
        and workspace_role == "member"
        and not is_global_admin
        and not grant_exists
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _create_tables() -> dict[str, sa.Table]:
    tool_sources = op.create_table(
        "tool_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("mcp_server_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "mcp_server_id"],
            ["mcp_servers.workspace_id", "mcp_servers.id"],
            name="fk_tool_sources_mcp_server_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_tool_sources_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "kind",
            "name",
            name="uq_tool_sources_workspace_kind_name",
        ),
        sa.UniqueConstraint(
            "workspace_id", "mcp_server_id", name="uq_tool_sources_mcp_server"
        ),
        sa.CheckConstraint(
            "kind IN ('builtin', 'python', 'mcp')",
            name="ck_tool_sources_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'archived')",
            name="ck_tool_sources_status",
        ),
        sa.CheckConstraint(
            "(kind = 'mcp' AND ((mcp_server_id IS NOT NULL "
            "AND status IN ('active', 'disabled')) OR "
            "(mcp_server_id IS NULL AND status = 'archived'))) OR "
            "(kind IN ('builtin', 'python') AND mcp_server_id IS NULL)",
            name="ck_tool_sources_mcp_server_kind",
        ),
    )
    for column in ("workspace_id", "mcp_server_id", "created_by_user_id"):
        op.create_index(f"ix_tool_sources_{column}", "tool_sources", [column])

    tools = op.create_table(
        "tools",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("stable_key", sa.String(255), nullable=False),
        sa.Column("function_name", sa.String(255), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "availability",
            sa.String(20),
            nullable=False,
            server_default="available",
        ),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["tool_sources.workspace_id", "tool_sources.id"],
            name="fk_tools_source_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_tools_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "function_name",
            name="uq_tools_workspace_function_name",
        ),
        sa.UniqueConstraint(
            "source_id", "stable_key", name="uq_tools_source_stable_key"
        ),
        sa.CheckConstraint(
            "kind IN ('builtin', 'python', 'mcp')",
            name="ck_tools_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'archived')",
            name="ck_tools_status",
        ),
        sa.CheckConstraint(
            "availability IN ('available', 'unavailable')",
            name="ck_tools_availability",
        ),
    )
    for column in (
        "workspace_id",
        "source_id",
        "current_version_id",
        "created_by_user_id",
    ):
        op.create_index(f"ix_tools_{column}", "tools", [column])

    tool_versions = op.create_table(
        "tool_versions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("tool_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=True),
        sa.Column("execution_spec", sa.JSON(), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tool_id"],
            ["tools.workspace_id", "tools.id"],
            name="fk_tool_versions_tool_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_tool_versions_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "tool_id",
            "id",
            name="uq_tool_versions_workspace_tool_id",
        ),
        sa.UniqueConstraint(
            "tool_id", "revision", name="uq_tool_versions_tool_revision"
        ),
        sa.UniqueConstraint(
            "tool_id",
            "definition_hash",
            name="uq_tool_versions_tool_definition_hash",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_tool_versions_revision"),
        sa.CheckConstraint(
            "length(definition_hash) = 64",
            name="ck_tool_versions_definition_hash",
        ),
    )
    for column in ("workspace_id", "tool_id", "created_by_user_id"):
        op.create_index(f"ix_tool_versions_{column}", "tool_versions", [column])

    op.create_foreign_key(
        "fk_tools_current_version_workspace",
        "tools",
        "tool_versions",
        ["workspace_id", "id", "current_version_id"],
        ["workspace_id", "tool_id", "id"],
    )

    tool_drafts = op.create_table(
        "tool_drafts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("tool_id", sa.String(36), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=True),
        sa.Column("execution_spec", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tool_id"],
            ["tools.workspace_id", "tools.id"],
            name="fk_tool_drafts_tool_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_tool_drafts_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id", "tool_id", name="uq_tool_drafts_tool"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_tool_drafts_revision"),
    )
    for column in ("workspace_id", "tool_id", "updated_by_user_id"):
        op.create_index(f"ix_tool_drafts_{column}", "tool_drafts", [column])

    tool_policies = op.create_table(
        "tool_policies",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("tool_id", sa.String(36), nullable=False),
        sa.Column("tool_version_id", sa.String(36), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("approval", sa.String(20), nullable=False),
        sa.Column("effect", sa.String(30), nullable=False),
        sa.Column(
            "allowed_access_sources",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("workflow_callable", sa.Boolean(), nullable=False),
        sa.Column("parallel_safe", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tool_id", "tool_version_id"],
            [
                "tool_versions.workspace_id",
                "tool_versions.tool_id",
                "tool_versions.id",
            ],
            name="fk_tool_policies_version_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_tool_policies_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id", "tool_id", name="uq_tool_policies_tool"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_tool_policies_revision"),
        sa.CheckConstraint(
            "length(definition_hash) = 64",
            name="ck_tool_policies_definition_hash",
        ),
        sa.CheckConstraint(
            "approval IN ('auto', 'each_call', 'disabled')",
            name="ck_tool_policies_approval",
        ),
        sa.CheckConstraint(
            "effect IN ('pure', 'external_read', 'external_write', 'unknown')",
            name="ck_tool_policies_effect",
        ),
    )
    for column in (
        "workspace_id",
        "tool_id",
        "tool_version_id",
        "reviewed_by_user_id",
    ):
        op.create_index(f"ix_tool_policies_{column}", "tool_policies", [column])

    application_tool_bindings = op.create_table(
        "application_tool_bindings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=False),
        sa.Column("tool_id", sa.String(36), nullable=False),
        sa.Column("tool_version_id", sa.String(36), nullable=False),
        sa.Column("bound_by_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "application_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_application_tool_bindings_application_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tool_id", "tool_version_id"],
            [
                "tool_versions.workspace_id",
                "tool_versions.tool_id",
                "tool_versions.id",
            ],
            name="fk_application_tool_bindings_version_workspace",
        ),
        sa.ForeignKeyConstraint(["bound_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_application_tool_bindings_workspace_id",
        ),
        sa.UniqueConstraint(
            "application_id",
            "tool_id",
            name="uq_application_tool_bindings_application_tool",
        ),
    )
    for column in (
        "workspace_id",
        "application_id",
        "tool_id",
        "tool_version_id",
        "bound_by_user_id",
    ):
        op.create_index(
            f"ix_application_tool_bindings_{column}",
            "application_tool_bindings",
            [column],
        )

    tool_invocations = op.create_table(
        "tool_invocations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("root_run_id", sa.String(36), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("invocation_id", sa.String(255), nullable=False),
        sa.Column("execution_user_id", sa.String(36), nullable=False),
        sa.Column("access_source", sa.String(20), nullable=False),
        sa.Column("tool_id", sa.String(36), nullable=False),
        sa.Column("tool_version_id", sa.String(36), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_task_id", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_data", sa.JSON(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "usage",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "root_run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_tool_invocations_root_run_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_tool_invocations_run_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "tool_id", "tool_version_id"],
            [
                "tool_versions.workspace_id",
                "tool_versions.tool_id",
                "tool_versions.id",
            ],
            name="fk_tool_invocations_version_workspace",
        ),
        sa.ForeignKeyConstraint(["execution_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_tool_invocations_workspace_id"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_tool_invocations_idempotency",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "origin",
            "run_id",
            "invocation_id",
            name="uq_tool_invocations_origin_run_invocation",
        ),
        sa.CheckConstraint(
            "origin IN ('test', 'agent', 'workflow')",
            name="ck_tool_invocations_origin",
        ),
        sa.CheckConstraint(
            "(origin = 'test' AND root_run_id IS NULL AND run_id IS NULL) OR "
            "(origin IN ('agent', 'workflow') AND root_run_id IS NOT NULL "
            "AND run_id IS NOT NULL)",
            name="ck_tool_invocations_origin_runs",
        ),
        sa.CheckConstraint(
            "access_source IN ('console', 'public', 'api')",
            name="ck_tool_invocations_access_source",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'awaiting_approval', 'approved', 'running', "
            "'succeeded', 'failed', 'rejected', 'uncertain', 'cancelled')",
            name="ck_tool_invocations_status",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('confirmed', 'uncertain')",
            name="ck_tool_invocations_outcome",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="ck_tool_invocations_attempts",
        ),
        sa.CheckConstraint(
            "length(arguments_hash) = 64",
            name="ck_tool_invocations_arguments_hash",
        ),
        sa.CheckConstraint(
            "(approved_by_user_id IS NULL AND approved_at IS NULL) OR "
            "(approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_tool_invocations_approval",
        ),
        sa.CheckConstraint(
            "lease_expires_at IS NULL OR worker_task_id IS NOT NULL",
            name="ck_tool_invocations_lease",
        ),
    )
    for column in (
        "workspace_id",
        "origin",
        "root_run_id",
        "run_id",
        "execution_user_id",
        "tool_id",
        "tool_version_id",
        "status",
        "approved_by_user_id",
        "worker_task_id",
        "lease_expires_at",
    ):
        op.create_index(
            f"ix_tool_invocations_{column}", "tool_invocations", [column]
        )

    return {
        "tool_sources": tool_sources,
        "tools": tools,
        "tool_drafts": tool_drafts,
        "tool_versions": tool_versions,
        "tool_policies": tool_policies,
        "application_tool_bindings": application_tool_bindings,
        "tool_invocations": tool_invocations,
    }


def _system_catalog_rows(
    workspace_id: str,
    timestamp: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    builtin_source_id = _stable_catalog_id(f"source:{workspace_id}:builtin")
    python_source_id = _stable_catalog_id(f"source:{workspace_id}:python")
    tool_id = _stable_catalog_id(f"tool:{workspace_id}:builtin:current_time")
    input_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {"iso8601": {"type": "string", "maxLength": 64}},
        "required": ["iso8601"],
        "additionalProperties": False,
    }
    execution_spec = {"builtin": "current_time"}
    definition_hash = _canonical_hash(
        {
            "name": "current_time",
            "description": "Return the current UTC time.",
            "input_schema": input_schema,
            "output_schema": output_schema,
            "execution_spec": execution_spec,
        }
    )
    version_id = _stable_catalog_id(f"version:{tool_id}:{definition_hash}")
    source_rows = [
        {
            "id": builtin_source_id,
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
            "id": python_source_id,
            "workspace_id": workspace_id,
            "mcp_server_id": None,
            "kind": "python",
            "name": "Python",
            "status": "active",
            "created_by_user_id": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    ]
    tool_row = {
        "id": tool_id,
        "workspace_id": workspace_id,
        "source_id": builtin_source_id,
        "kind": "builtin",
        "stable_key": "current_time",
        "function_name": "current_time",
        "current_version_id": None,
        "status": "active",
        "availability": "available",
        "created_by_user_id": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    version_row = {
        "id": version_id,
        "workspace_id": workspace_id,
        "tool_id": tool_id,
        "revision": 1,
        "display_name": "Current time",
        "description": "Return the current UTC time.",
        "input_schema": input_schema,
        "output_schema": output_schema,
        "execution_spec": execution_spec,
        "definition_hash": definition_hash,
        "created_by_user_id": None,
        "created_at": timestamp,
    }
    policy_row = {
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
        "parallel_safe": True,
        "reviewed_by_user_id": None,
        "reviewed_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return source_rows, tool_row, version_row, policy_row


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _backfill(bind: sa.Connection, tables: dict[str, sa.Table]) -> None:
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.String(36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    mcp_servers = sa.table(
        "mcp_servers",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("name", sa.String(120)),
        sa.column("status", sa.String(20)),
        sa.column("tools", sa.JSON()),
        sa.column("created_by_user_id", sa.String(36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    agents = sa.table(
        "agents",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("created_by_user_id", sa.String(36)),
        sa.column("published_snapshot", sa.JSON()),
    )
    agent_mcp_tools = sa.table(
        "agent_mcp_tools",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("agent_id", sa.String(36)),
        sa.column("mcp_server_id", sa.String(36)),
        sa.column("tool_name", sa.String(255)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    agent_runs = sa.table(
        "agent_runs",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("agent_id", sa.String(36)),
        sa.column("mcp_tools", sa.JSON()),
    )
    workflow_definitions = sa.table(
        "workflow_definitions",
        sa.column("workspace_id", sa.String(36)),
        sa.column("agent_id", sa.String(36)),
        sa.column("graph", sa.JSON()),
    )
    workflow_versions = sa.table(
        "workflow_versions",
        sa.column("workspace_id", sa.String(36)),
        sa.column("agent_id", sa.String(36)),
        sa.column("graph", sa.JSON()),
    )
    workflow_run_details = sa.table(
        "workflow_run_details",
        sa.column("workspace_id", sa.String(36)),
        sa.column("run_id", sa.String(36)),
        sa.column("graph_snapshot", sa.JSON()),
    )
    legacy_policies = sa.table(
        "mcp_tool_policies",
        sa.column("workspace_id", sa.String(36)),
        sa.column("mcp_server_id", sa.String(36)),
        sa.column("tool_name", sa.String(255)),
        sa.column("definition_hash", sa.String(64)),
        sa.column("mode", sa.String(30)),
        sa.column("reviewed_by_user_id", sa.String(36)),
        sa.column("reviewed_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    resource_permissions = sa.table(
        "resource_permissions",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("resource_type", sa.String(40)),
        sa.column("resource_id", sa.String(36)),
        sa.column("user_id", sa.String(36)),
        sa.column("permission", sa.String(20)),
        sa.column("created_by_user_id", sa.String(36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    memberships = sa.table(
        "workspace_memberships",
        sa.column("workspace_id", sa.String(36)),
        sa.column("user_id", sa.String(36)),
        sa.column("role", sa.String(20)),
    )
    users = sa.table(
        "users",
        sa.column("id", sa.String(36)),
        sa.column("is_global_admin", sa.Boolean()),
    )

    timestamp = _now()
    workspace_rows = list(
        bind.execute(sa.select(workspaces.c.id, workspaces.c.created_at)).mappings()
    )
    server_rows = list(bind.execute(sa.select(mcp_servers)).mappings())
    server_by_key = {
        (row["workspace_id"], row["id"]): row for row in server_rows
    }
    definitions: dict[tuple[str, str, str], dict[str, Any]] = {}
    references: dict[tuple[str, str, str], str | None] = {}

    for server in server_rows:
        discovered = _json_value(server["tools"])
        if not isinstance(discovered, list):
            continue
        for item in discovered:
            if not isinstance(item, dict):
                continue
            tool_name = item.get("name")
            if not isinstance(tool_name, str) or not tool_name:
                continue
            key = (server["workspace_id"], server["id"], tool_name)
            definitions[key] = item
            _add_reference(references, *key, server["created_by_user_id"])

    binding_rows = list(
        bind.execute(
            sa.select(
                agent_mcp_tools.c.id,
                agent_mcp_tools.c.workspace_id,
                agent_mcp_tools.c.agent_id,
                agent_mcp_tools.c.mcp_server_id,
                agent_mcp_tools.c.tool_name,
                agent_mcp_tools.c.created_at,
                agents.c.created_by_user_id,
            ).select_from(
                agent_mcp_tools.join(
                    agents,
                    sa.and_(
                        agent_mcp_tools.c.workspace_id == agents.c.workspace_id,
                        agent_mcp_tools.c.agent_id == agents.c.id,
                    ),
                )
            )
        ).mappings()
    )
    for row in binding_rows:
        _add_reference(
            references,
            row["workspace_id"],
            row["mcp_server_id"],
            row["tool_name"],
            row["created_by_user_id"],
        )

    for row in bind.execute(
        sa.select(
            agents.c.workspace_id,
            agents.c.created_by_user_id,
            agents.c.published_snapshot,
        )
    ).mappings():
        for server_id, tool_name in _extract_mcp_references(
            _json_value(row["published_snapshot"])
        ):
            _add_reference(
                references,
                row["workspace_id"],
                server_id,
                tool_name,
                row["created_by_user_id"],
            )

    for row in bind.execute(
        sa.select(
            agent_runs.c.workspace_id,
            agent_runs.c.mcp_tools,
            agents.c.created_by_user_id,
        ).select_from(
            agent_runs.join(
                agents,
                sa.and_(
                    agent_runs.c.workspace_id == agents.c.workspace_id,
                    agent_runs.c.agent_id == agents.c.id,
                ),
            )
        )
    ).mappings():
        for server_id, tool_name in _extract_mcp_references(
            _json_value(row["mcp_tools"])
        ):
            _add_reference(
                references,
                row["workspace_id"],
                server_id,
                tool_name,
                row["created_by_user_id"],
            )

    for graph_table in (workflow_definitions, workflow_versions):
        for row in bind.execute(
            sa.select(
                graph_table.c.workspace_id,
                graph_table.c.graph,
                agents.c.created_by_user_id,
            ).select_from(
                graph_table.join(
                    agents,
                    sa.and_(
                        graph_table.c.workspace_id == agents.c.workspace_id,
                        graph_table.c.agent_id == agents.c.id,
                    ),
                )
            )
        ).mappings():
            for server_id, tool_name in _extract_mcp_references(
                _json_value(row["graph"])
            ):
                _add_reference(
                    references,
                    row["workspace_id"],
                    server_id,
                    tool_name,
                    row["created_by_user_id"],
                )

    for row in bind.execute(
        sa.select(
            workflow_run_details.c.workspace_id,
            workflow_run_details.c.graph_snapshot,
            agents.c.created_by_user_id,
        ).select_from(
            workflow_run_details.join(
                agent_runs,
                sa.and_(
                    workflow_run_details.c.workspace_id
                    == agent_runs.c.workspace_id,
                    workflow_run_details.c.run_id == agent_runs.c.id,
                ),
            ).join(
                agents,
                sa.and_(
                    agent_runs.c.workspace_id == agents.c.workspace_id,
                    agent_runs.c.agent_id == agents.c.id,
                ),
            )
        )
    ).mappings():
        for server_id, tool_name in _extract_mcp_references(
            _json_value(row["graph_snapshot"])
        ):
            _add_reference(
                references,
                row["workspace_id"],
                server_id,
                tool_name,
                row["created_by_user_id"],
            )

    legacy_policy_rows = list(bind.execute(sa.select(legacy_policies)).mappings())
    legacy_policy_by_key = {
        (row["workspace_id"], row["mcp_server_id"], row["tool_name"]): row
        for row in legacy_policy_rows
    }
    _add_legacy_policy_references(references, legacy_policy_rows, server_by_key)

    source_rows: dict[str, dict[str, Any]] = {}
    tool_rows: dict[str, dict[str, Any]] = {}
    version_rows: dict[str, dict[str, Any]] = {}
    policy_rows: dict[str, dict[str, Any]] = {}
    current_versions: dict[str, str] = {}
    tool_refs: dict[tuple[str, str, str], tuple[str, str, str | None]] = {}

    for workspace in workspace_rows:
        created_at = workspace["created_at"] or timestamp
        sources, tool, version, policy = _system_catalog_rows(
            workspace["id"], created_at
        )
        source_rows.update((row["id"], row) for row in sources)
        tool_rows[tool["id"]] = tool
        version_rows[version["id"]] = version
        policy_rows[policy["id"]] = policy
        current_versions[tool["id"]] = version["id"]

    for server in server_rows:
        source_id = _stable_catalog_id(
            f"source:{server['workspace_id']}:mcp:{server['id']}"
        )
        source_rows[source_id] = {
            "id": source_id,
            "workspace_id": server["workspace_id"],
            "mcp_server_id": server["id"],
            "kind": "mcp",
            "name": server["name"],
            "status": "disabled" if server["status"] == "disabled" else "active",
            "created_by_user_id": server["created_by_user_id"],
            "created_at": server["created_at"] or timestamp,
            "updated_at": server["updated_at"] or timestamp,
        }

    for key in sorted(references):
        workspace_id, server_id, tool_name = key
        server = server_by_key.get((workspace_id, server_id))
        owner_id = server["created_by_user_id"] if server else references[key]
        source_id = _stable_catalog_id(
            f"source:{workspace_id}:mcp:{server_id}"
        )
        if source_id not in source_rows:
            source_rows[source_id] = {
                "id": source_id,
                "workspace_id": workspace_id,
                "mcp_server_id": None,
                "kind": "mcp",
                "name": f"Unavailable MCP {server_id}"[:120],
                "status": "archived",
                "created_by_user_id": owner_id,
                "created_at": timestamp,
                "updated_at": timestamp,
            }

        definition = definitions.get(key)
        available = _mcp_tool_available(definition, server)
        if definition is None:
            definition = {
                "name": tool_name,
                "description": "",
                "input_schema": {"type": "object"},
                "annotations": None,
            }
        definition_hash = _mcp_definition_hash(definition)
        tool_id = _stable_catalog_id(
            f"tool:{workspace_id}:mcp:{server_id}:{tool_name}"
        )
        version_id = _stable_catalog_id(
            f"version:{tool_id}:{definition_hash}"
        )
        created_at = server["created_at"] if server else timestamp
        updated_at = server["updated_at"] if server else timestamp
        tool_rows[tool_id] = {
            "id": tool_id,
            "workspace_id": workspace_id,
            "source_id": source_id,
            "kind": "mcp",
            "stable_key": tool_name,
            "function_name": _mcp_function_name(server_id, tool_name),
            "current_version_id": None,
            "status": "active" if server else "archived",
            "availability": "available" if available else "unavailable",
            "created_by_user_id": owner_id,
            "created_at": created_at or timestamp,
            "updated_at": updated_at or timestamp,
        }
        version_rows[version_id] = {
            "id": version_id,
            "workspace_id": workspace_id,
            "tool_id": tool_id,
            "revision": 1,
            "display_name": tool_name[:120],
            "description": str(definition.get("description") or ""),
            "input_schema": _mcp_input_schema(definition),
            "output_schema": None,
            "execution_spec": (
                {"server_id": server_id, "tool_name": tool_name}
                if server
                else {"legacy_server_id": server_id, "tool_name": tool_name}
            ),
            "definition_hash": definition_hash,
            "created_by_user_id": owner_id,
            "created_at": created_at or timestamp,
        }
        current_versions[tool_id] = version_id
        tool_refs[key] = (tool_id, version_id, owner_id)

        legacy_policy = legacy_policy_by_key.get(key)
        mode = legacy_policy["mode"] if legacy_policy else "approval_required"
        if mode == "read_only":
            approval = "auto"
            effect = "external_read"
            allowed_access_sources = ["console", "public", "api"]
            workflow_callable = True
            parallel_safe = True
        elif mode == "disabled":
            approval = "disabled"
            effect = "unknown"
            allowed_access_sources = []
            workflow_callable = False
            parallel_safe = False
        else:
            approval = "each_call"
            effect = "unknown"
            allowed_access_sources = ["console"]
            workflow_callable = False
            parallel_safe = False
        policy_rows[_stable_catalog_id(f"policy:{tool_id}")] = {
            "id": _stable_catalog_id(f"policy:{tool_id}"),
            "workspace_id": workspace_id,
            "tool_id": tool_id,
            "tool_version_id": version_id,
            "definition_hash": (
                legacy_policy["definition_hash"]
                if legacy_policy
                else definition_hash
            ),
            "revision": 1,
            "approval": approval,
            "effect": effect,
            "allowed_access_sources": allowed_access_sources,
            "workflow_callable": workflow_callable,
            "parallel_safe": parallel_safe,
            "reviewed_by_user_id": (
                legacy_policy["reviewed_by_user_id"] if legacy_policy else None
            ),
            "reviewed_at": (
                legacy_policy["reviewed_at"] if legacy_policy else None
            ),
            "created_at": (
                legacy_policy["created_at"] if legacy_policy else timestamp
            ),
            "updated_at": (
                legacy_policy["updated_at"] if legacy_policy else timestamp
            ),
        }

    if source_rows:
        bind.execute(tables["tool_sources"].insert(), list(source_rows.values()))
    if tool_rows:
        bind.execute(tables["tools"].insert(), list(tool_rows.values()))
    if version_rows:
        bind.execute(tables["tool_versions"].insert(), list(version_rows.values()))
    for tool_id, version_id in current_versions.items():
        bind.execute(
            tables["tools"]
            .update()
            .where(tables["tools"].c.id == tool_id)
            .values(current_version_id=version_id)
        )
    if policy_rows:
        bind.execute(tables["tool_policies"].insert(), list(policy_rows.values()))

    application_bindings: dict[str, dict[str, Any]] = {}
    grant_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    membership_roles = {
        (row["workspace_id"], row["user_id"]): row["role"]
        for row in bind.execute(sa.select(memberships)).mappings()
    }
    global_admin_ids = {
        row["id"]
        for row in bind.execute(
            sa.select(users.c.id).where(users.c.is_global_admin.is_(True))
        ).mappings()
    }
    existing_grants = {
        (row["workspace_id"], row["resource_id"], row["user_id"])
        for row in bind.execute(
            sa.select(
                resource_permissions.c.workspace_id,
                resource_permissions.c.resource_id,
                resource_permissions.c.user_id,
            ).where(resource_permissions.c.resource_type == "tool")
        ).mappings()
    }
    for binding in binding_rows:
        key = (
            binding["workspace_id"],
            binding["mcp_server_id"],
            binding["tool_name"],
        )
        tool_ref = tool_refs.get(key)
        if tool_ref is None:
            continue
        tool_id, version_id, tool_owner_id = tool_ref
        bound_by_user_id = binding["created_by_user_id"]
        binding_id = _stable_catalog_id(
            f"binding:{binding['agent_id']}:{tool_id}"
        )
        application_bindings[binding_id] = {
            "id": binding_id,
            "workspace_id": binding["workspace_id"],
            "application_id": binding["agent_id"],
            "tool_id": tool_id,
            "tool_version_id": version_id,
            "bound_by_user_id": bound_by_user_id,
            "created_at": binding["created_at"] or timestamp,
        }
        grant_key = (binding["workspace_id"], tool_id, bound_by_user_id)
        if _should_backfill_use_grant(
            bound_by_user_id=bound_by_user_id,
            tool_owner_id=tool_owner_id,
            workspace_role=membership_roles.get(
                (binding["workspace_id"], bound_by_user_id)
            ),
            is_global_admin=bound_by_user_id in global_admin_ids,
            grant_exists=grant_key in existing_grants,
        ):
            grant_rows[grant_key] = {
                "id": _stable_catalog_id(
                    f"grant:tool:{binding['workspace_id']}:{tool_id}:{bound_by_user_id}"
                ),
                "workspace_id": binding["workspace_id"],
                "resource_type": "tool",
                "resource_id": tool_id,
                "user_id": bound_by_user_id,
                "permission": "use",
                "created_by_user_id": bound_by_user_id,
                "created_at": binding["created_at"] or timestamp,
                "updated_at": binding["created_at"] or timestamp,
            }
    if application_bindings:
        bind.execute(
            tables["application_tool_bindings"].insert(),
            list(application_bindings.values()),
        )
    if grant_rows:
        bind.execute(resource_permissions.insert(), list(grant_rows.values()))


def upgrade() -> None:
    tables = _create_tables()
    op.execute(
        sa.text(
            "UPDATE resource_permissions SET permission = 'view' "
            "WHERE resource_type = 'agent' AND permission = 'edit'"
        )
    )
    with op.batch_alter_table("resource_permissions") as batch:
        batch.drop_constraint(
            "ck_resource_permissions_resource_type",
            type_="check",
        )
        batch.drop_constraint(
            "ck_resource_permissions_permission",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_resource_permissions_type_permission",
            "(resource_type = 'knowledge_base' AND permission IN ('view', 'edit')) OR "
            "(resource_type = 'agent' AND permission = 'view') OR "
            "(resource_type = 'tool' AND permission IN ('view', 'use'))",
        )
    _backfill(op.get_bind(), tables)


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM resource_permissions WHERE resource_type = 'tool'")
    )
    with op.batch_alter_table("resource_permissions") as batch:
        batch.drop_constraint(
            "ck_resource_permissions_type_permission",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_resource_permissions_resource_type",
            "resource_type IN ('knowledge_base', 'agent')",
        )
        batch.create_check_constraint(
            "ck_resource_permissions_permission",
            "permission IN ('view', 'edit')",
        )

    op.drop_constraint(
        "fk_tools_current_version_workspace",
        "tools",
        type_="foreignkey",
    )
    for table_name in (
        "tool_invocations",
        "application_tool_bindings",
        "tool_policies",
        "tool_drafts",
        "tool_versions",
        "tools",
        "tool_sources",
    ):
        op.drop_table(table_name)
