"""Add immutable Agent publication versions and Run snapshots.

Revision ID: 202608160005
Revises: 202608160004
Create Date: 2026-08-17
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "202608160005"
down_revision: str | None = "202608160004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PUBLICATION_NAMESPACE = UUID("b3d62393-5420-4810-ab0d-dccb2ac2cf44")
_TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}
_MIGRATION_MARKER = "_agent_publication_migration"


def _agent_run_requires_drain(run_status: str, app_type: str) -> bool:
    return app_type == "agent" and run_status not in _TERMINAL_RUN_STATUSES


def _assert_agent_runs_drained(bind: sa.Connection) -> None:
    agents = sa.table(
        "agents",
        sa.column("id", sa.String(36)),
        sa.column("app_type", sa.String(20)),
    )
    runs = sa.table(
        "agent_runs",
        sa.column("id", sa.String(36)),
        sa.column("agent_id", sa.String(36)),
        sa.column("status", sa.String(20)),
    )
    active_run_id = bind.execute(
        sa.select(runs.c.id)
        .select_from(runs.join(agents, agents.c.id == runs.c.agent_id))
        .where(
            agents.c.app_type == "agent",
            runs.c.status.not_in(sorted(_TERMINAL_RUN_STATUSES)),
        )
        .limit(1)
    ).scalar_one_or_none()
    if active_run_id is not None:
        raise RuntimeError(
            "Agent Runs must be drained before upgrading unified Tool execution."
        )


def _stable_id(key: str) -> str:
    return str(uuid5(_PUBLICATION_NAMESPACE, key))


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return fallback
    return value if value is not None else fallback


def _interaction_config(value: Any) -> dict[str, Any]:
    raw = _json_value(value, {})
    if not isinstance(raw, Mapping):
        raw = {}
    upload = raw.get("file_upload_setting")
    if not isinstance(upload, Mapping):
        upload = {}
    file_types = upload.get("file_upload_type", ["document", "image"])
    if not isinstance(file_types, list):
        file_types = ["document", "image"]
    return {
        "prologue": str(raw.get("prologue") or ""),
        "tts_type": str(raw.get("tts_type") or "BROWSER"),
        "file_upload": bool(raw.get("file_upload", False)),
        "file_upload_setting": {"file_upload_type": file_types},
        "user_input_title": str(raw.get("user_input_title") or ""),
    }


def _canonical_hash(
    configuration_snapshot: dict[str, Any],
    resource_snapshot: dict[str, Any],
) -> str:
    encoded = json.dumps(
        {
            "schema_version": 1,
            "configuration": configuration_snapshot,
            "resources": resource_snapshot,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mcp_references(value: Any) -> list[tuple[str, str]]:
    raw = _json_value(value, [])
    if not isinstance(raw, list):
        return []
    references: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        server_id = item.get("server_id")
        tool_name = item.get("tool_name")
        if isinstance(server_id, str) and server_id and isinstance(tool_name, str) and tool_name:
            references.append((server_id, tool_name))
    return sorted(set(references))


def _legacy_publication_snapshot(
    configuration: Mapping[str, Any],
    resources: Mapping[str, Any],
) -> dict[str, Any]:
    references: list[dict[str, str]] = []
    tools = resources.get("tools", [])
    for snapshot in tools if isinstance(tools, list) else []:
        if not isinstance(snapshot, Mapping) or snapshot.get("kind") != "mcp":
            raise RuntimeError(
                "Agent publication cannot be represented by the legacy schema."
            )
        execution_spec = snapshot.get("execution_spec", {})
        if not isinstance(execution_spec, Mapping):
            raise RuntimeError(
                "Agent publication cannot be represented by the legacy schema."
            )
        server_id = execution_spec.get("server_id") or execution_spec.get(
            "legacy_server_id"
        )
        tool_name = execution_spec.get("tool_name")
        if not isinstance(server_id, str) or not isinstance(tool_name, str):
            raise RuntimeError(
                "Agent publication cannot be represented by the legacy schema."
            )
        references.append({"server_id": server_id, "tool_name": tool_name})
    knowledge_ids = resources.get("knowledge_base_ids", [])
    if not isinstance(knowledge_ids, list):
        raise RuntimeError("Agent publication knowledge references are invalid.")
    return {
        "name": str(configuration["name"]),
        "description": str(configuration.get("description", "")),
        "instructions": str(configuration["instructions"]),
        "model_id": str(configuration["model_id"]),
        "knowledge_query_mode": str(configuration["knowledge_query_mode"]),
        "knowledge_base_ids": sorted({str(item) for item in knowledge_ids}),
        "mcp_tools": sorted(
            references,
            key=lambda item: (item["server_id"], item["tool_name"]),
        ),
        "interaction_config": dict(configuration.get("interaction_config", {})),
    }


def _permission_backfill_action(permission: str | None) -> str:
    return "insert" if permission is None else "keep"


def _configuration(row: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": str(snapshot.get("name", row["name"])),
        "description": str(snapshot.get("description", row["description"]) or ""),
        "instructions": str(snapshot.get("instructions", row["instructions"])),
        "model_id": str(snapshot.get("model_id", row["model_id"])),
        "knowledge_query_mode": str(
            snapshot.get("knowledge_query_mode", row["knowledge_query_mode"])
        ),
        "interaction_config": _interaction_config(
            snapshot.get("interaction_config", row["interaction_config"])
        ),
    }


def _tool_catalog(
    bind: sa.Connection,
) -> tuple[
    dict[tuple[str, str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str, str, str], dict[str, Any]],
    dict[tuple[str, str], str | None],
]:
    sources = sa.table(
        "tool_sources",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("mcp_server_id", sa.String(36)),
        sa.column("kind", sa.String(20)),
    )
    tools = sa.table(
        "tools",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("source_id", sa.String(36)),
        sa.column("kind", sa.String(20)),
        sa.column("function_name", sa.String(80)),
        sa.column("current_version_id", sa.String(36)),
        sa.column("created_by_user_id", sa.String(36)),
    )
    versions = sa.table(
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
    policies = sa.table(
        "tool_policies",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("tool_version_id", sa.String(36)),
        sa.column("revision", sa.Integer()),
        sa.column("approval", sa.String(20)),
        sa.column("effect", sa.String(30)),
        sa.column("allowed_access_sources", sa.JSON()),
        sa.column("workflow_callable", sa.Boolean()),
        sa.column("parallel_safe", sa.Boolean()),
    )
    rows = bind.execute(
        sa.select(
            sources.c.id.label("source_id"),
            sources.c.workspace_id.label("workspace_id"),
            sources.c.kind.label("source_kind"),
            tools.c.id.label("tool_id"),
            tools.c.kind.label("tool_kind"),
            tools.c.function_name.label("function_name"),
            tools.c.current_version_id.label("current_version_id"),
            tools.c.created_by_user_id.label("tool_owner_id"),
            versions.c.id.label("version_id"),
            versions.c.display_name.label("display_name"),
            versions.c.description.label("description"),
            versions.c.input_schema.label("input_schema"),
            versions.c.output_schema.label("output_schema"),
            versions.c.execution_spec.label("execution_spec"),
            versions.c.definition_hash.label("definition_hash"),
            policies.c.id.label("policy_id"),
            policies.c.revision.label("policy_revision"),
            policies.c.approval.label("approval"),
            policies.c.effect.label("effect"),
            policies.c.allowed_access_sources.label("allowed_access_sources"),
            policies.c.workflow_callable.label("workflow_callable"),
            policies.c.parallel_safe.label("parallel_safe"),
        )
        .select_from(
            tools.join(
                sources,
                sa.and_(
                    sources.c.workspace_id == tools.c.workspace_id,
                    sources.c.id == tools.c.source_id,
                ),
            )
            .join(
                versions,
                sa.and_(
                    versions.c.workspace_id == tools.c.workspace_id,
                    versions.c.tool_id == tools.c.id,
                ),
            )
            .join(
                policies,
                sa.and_(
                    policies.c.workspace_id == tools.c.workspace_id,
                    policies.c.tool_id == tools.c.id,
                ),
            )
        )
    ).mappings()
    catalog: dict[tuple[str, str, str], dict[str, Any]] = {}
    catalog_by_version: dict[tuple[str, str], dict[str, Any]] = {}
    catalog_by_definition: dict[
        tuple[str, str, str, str], dict[str, Any]
    ] = {}
    tool_owners: dict[tuple[str, str], str | None] = {}
    for row in rows:
        execution_spec = _json_value(row["execution_spec"], {})
        if not isinstance(execution_spec, Mapping):
            continue
        snapshot = {
            "schema_version": 1,
            "tool_id": row["tool_id"],
            "version_id": row["version_id"],
            "source_id": row["source_id"],
            "kind": row["tool_kind"],
            "function_name": row["function_name"],
            "display_name": row["display_name"],
            "description": row["description"],
            "input_schema": _json_value(row["input_schema"], {}),
            "output_schema": _json_value(row["output_schema"], None),
            "definition_hash": row["definition_hash"],
            "policy_id": row["policy_id"],
            "policy_revision": row["policy_revision"],
            "approval": row["approval"],
            "effect": row["effect"],
            "allowed_access_sources": _json_value(row["allowed_access_sources"], []),
            "workflow_callable": row["workflow_callable"],
            "parallel_safe": row["parallel_safe"],
            "execution_spec": dict(execution_spec),
        }
        catalog_by_version[(row["tool_id"], row["version_id"])] = snapshot
        tool_owners[(row["workspace_id"], row["tool_id"])] = row["tool_owner_id"]
        if row["source_kind"] != "mcp":
            continue
        server_id = execution_spec.get("server_id") or execution_spec.get(
            "legacy_server_id"
        )
        tool_name = execution_spec.get("tool_name")
        if not isinstance(server_id, str) or not isinstance(tool_name, str):
            continue
        catalog_by_definition[
            (
                row["workspace_id"],
                server_id,
                tool_name,
                row["definition_hash"],
            )
        ] = snapshot
        if row["version_id"] == row["current_version_id"]:
            catalog[(row["workspace_id"], server_id, tool_name)] = snapshot
    return catalog, catalog_by_version, catalog_by_definition, tool_owners


def _binding_users(bind: sa.Connection) -> dict[tuple[str, str, str], str]:
    bindings = sa.table(
        "application_tool_bindings",
        sa.column("workspace_id", sa.String(36)),
        sa.column("application_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("tool_version_id", sa.String(36)),
        sa.column("bound_by_user_id", sa.String(36)),
    )
    return {
        (row["workspace_id"], row["application_id"], row["tool_id"]): row[
            "bound_by_user_id"
        ]
        for row in bind.execute(sa.select(bindings)).mappings()
    }


def _tool_snapshots(
    workspace_id: str,
    agent_id: str,
    owner_id: str,
    references: list[tuple[str, str]],
    catalog: Mapping[tuple[str, str, str], dict[str, Any]],
    binders: Mapping[tuple[str, str, str], str],
    fallback_grants: dict[tuple[str, str, str], dict[str, Any]] | None = None,
    created_at: datetime | None = None,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for server_id, tool_name in references:
        item = catalog.get((workspace_id, server_id, tool_name))
        if item is None:
            raise RuntimeError("Legacy Agent Tool reference could not be materialized.")
        snapshot = dict(item)
        binder = binders.get((workspace_id, agent_id, snapshot["tool_id"]))
        if binder is None:
            binder = owner_id
            if fallback_grants is not None and created_at is not None:
                grant = fallback_grants.setdefault(
                    (workspace_id, snapshot["tool_id"], binder),
                    {"created_at": created_at, "agent_ids": set()},
                )
                grant["agent_ids"].add(agent_id)
        snapshot["bound_by_user_id"] = binder
        snapshots.append(snapshot)
    return sorted(snapshots, key=lambda item: (item["tool_id"], item["version_id"]))


def _run_tool_snapshots(
    workspace_id: str,
    agent_id: str,
    owner_id: str,
    references: list[tuple[str, str]],
    calls: list[Mapping[str, Any]],
    catalog: Mapping[tuple[str, str, str], dict[str, Any]],
    catalog_by_definition: Mapping[
        tuple[str, str, str, str], dict[str, Any]
    ],
    bound_snapshots: list[dict[str, Any]],
    binders: Mapping[tuple[str, str, str], str],
    fallback_grants: dict[tuple[str, str, str], dict[str, Any]] | None,
    created_at: datetime,
) -> list[dict[str, Any]]:
    selected = dict(catalog)
    reference_set = set(references)
    for snapshot in bound_snapshots:
        execution_spec = snapshot.get("execution_spec", {})
        if not isinstance(execution_spec, Mapping):
            continue
        server_id = execution_spec.get("server_id") or execution_spec.get(
            "legacy_server_id"
        )
        tool_name = execution_spec.get("tool_name")
        reference = (server_id, tool_name)
        if reference in reference_set:
            selected[(workspace_id, server_id, tool_name)] = snapshot

    call_versions: dict[tuple[str, str], str] = {}
    for call in calls:
        if call["tool_kind"] != "mcp":
            continue
        matches: list[tuple[tuple[str, str], dict[str, Any]]] = []
        for server_id, tool_name in references:
            snapshot = catalog_by_definition.get(
                (workspace_id, server_id, tool_name, call["definition_hash"])
            )
            if snapshot is not None and snapshot["function_name"] == call["tool_name"]:
                matches.append(((server_id, tool_name), snapshot))
        if len(matches) != 1:
            raise RuntimeError(
                "Legacy Agent Tool call version could not be materialized uniquely."
            )
        reference, snapshot = matches[0]
        previous_version = call_versions.setdefault(reference, snapshot["version_id"])
        if previous_version != snapshot["version_id"]:
            raise RuntimeError("Legacy Agent Run contains multiple Tool versions.")
        selected[(workspace_id, *reference)] = snapshot

    return _tool_snapshots(
        workspace_id,
        agent_id,
        owner_id,
        references,
        selected,
        binders,
        fallback_grants,
        created_at,
    )


def _revoked_tool_grants(bind: sa.Connection) -> set[tuple[str, str]]:
    audit_logs = sa.table(
        "audit_logs",
        sa.column("action", sa.String(80)),
        sa.column("resource_type", sa.String(40)),
        sa.column("resource_id", sa.String(36)),
        sa.column("details", sa.JSON()),
    )
    revoked: set[tuple[str, str]] = set()
    for row in bind.execute(
        sa.select(audit_logs.c.resource_id, audit_logs.c.details).where(
            audit_logs.c.action == "resource_permission.revoke",
            audit_logs.c.resource_type == "tool",
        )
    ).mappings():
        details = row["details"]
        if isinstance(details, Mapping) and isinstance(details.get("user_id"), str):
            revoked.add((row["resource_id"], details["user_id"]))
    return revoked


def _membership_history_revokes_fallback_grant(
    action: str,
    details: Any,
) -> bool:
    if action == "workspace.member.remove":
        return True
    if action != "workspace.member.update" or not isinstance(details, Mapping):
        return False
    return details.get("previous_role") == "admin" and details.get("role") == "member"


def _revoked_fallback_binder_memberships(
    bind: sa.Connection,
) -> set[tuple[str, str]]:
    audit_logs = sa.table(
        "audit_logs",
        sa.column("workspace_id", sa.String(36)),
        sa.column("action", sa.String(80)),
        sa.column("resource_type", sa.String(40)),
        sa.column("resource_id", sa.String(36)),
        sa.column("details", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    revoked: set[tuple[str, str]] = set()
    for row in bind.execute(
        sa.select(
            audit_logs.c.workspace_id,
            audit_logs.c.action,
            audit_logs.c.resource_id,
            audit_logs.c.details,
            audit_logs.c.created_at,
        ).where(audit_logs.c.resource_type == "workspace_member")
    ).mappings():
        workspace_id = row["workspace_id"]
        if (
            not isinstance(workspace_id, str)
            or not _membership_history_revokes_fallback_grant(
                row["action"], row["details"]
            )
        ):
            continue
        revoked.add((workspace_id, row["resource_id"]))
    return revoked


def _backfill_snapshot_use_grants(
    bind: sa.Connection,
    fallback_grants: Mapping[tuple[str, str, str], Mapping[str, Any]],
    tool_owners: Mapping[tuple[str, str], str | None],
) -> dict[str, dict[str, set[tuple[str, str, datetime, datetime]]]]:
    if not fallback_grants:
        return {}
    permissions = sa.table(
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
        sa.column("is_active", sa.Boolean()),
        sa.column("is_global_admin", sa.Boolean()),
    )
    user_rows = {
        row["id"]: row for row in bind.execute(sa.select(users)).mappings()
    }
    roles = {
        (row["workspace_id"], row["user_id"]): row["role"]
        for row in bind.execute(sa.select(memberships)).mappings()
    }
    existing = {
        (row["workspace_id"], row["resource_id"], row["user_id"]): row
        for row in bind.execute(
            sa.select(permissions).where(permissions.c.resource_type == "tool")
        ).mappings()
    }
    revoked = _revoked_tool_grants(bind)
    membership_revocations = _revoked_fallback_binder_memberships(bind)
    markers: dict[str, dict[str, set[tuple[str, str, datetime, datetime]]]] = {}
    for key, grant in fallback_grants.items():
        workspace_id, tool_id, user_id = key
        timestamp = grant["created_at"]
        agent_ids = grant["agent_ids"]
        user = user_rows.get(user_id)
        if (
            user is None
            or not user["is_active"]
            or user["is_global_admin"]
            or roles.get((workspace_id, user_id)) != "member"
            or tool_owners.get((workspace_id, tool_id)) == user_id
        ):
            continue
        permission = existing.get(key)
        action = _permission_backfill_action(
            permission["permission"] if permission is not None else None
        )
        if action == "keep":
            continue
        if (tool_id, user_id) in revoked:
            # A revoke audit event proves the user's access was explicitly
            # removed; the missing permission row is revocation state, not
            # pre-grant history. Re-granting would resurrect revoked access.
            continue
        if (workspace_id, user_id) in membership_revocations:
            # A post-publication member removal or privilege reduction must
            # not become a new explicit Tool grant when the user later rejoins.
            continue
        permission_id = (
            permission["id"]
            if permission is not None
            else _stable_id(f"agent-publication-grant:{tool_id}:{user_id}")
        )
        for agent_id in agent_ids:
            markers.setdefault(agent_id, {}).setdefault(
                "inserted_use_grants",
                set(),
            ).add((permission_id, user_id, timestamp, timestamp))
        bind.execute(
            permissions.insert().values(
                id=permission_id,
                workspace_id=workspace_id,
                resource_type="tool",
                resource_id=tool_id,
                user_id=user_id,
                permission="use",
                created_by_user_id=user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    return markers


def _record_grant_markers(
    bind: sa.Connection,
    markers: Mapping[
        str, Mapping[str, set[tuple[str, str, datetime, datetime]]]
    ],
) -> None:
    if not markers:
        return
    agents = sa.table(
        "agents",
        sa.column("id", sa.String(36)),
        sa.column("published_snapshot", sa.JSON()),
    )
    for agent_id, values in markers.items():
        snapshot = bind.execute(
            sa.select(agents.c.published_snapshot).where(agents.c.id == agent_id)
        ).scalar_one()
        snapshot = _json_value(snapshot, {})
        if not isinstance(snapshot, Mapping):
            snapshot = {}
        updated = dict(snapshot)
        updated[_MIGRATION_MARKER] = {
            key: [
                {
                    "id": item[0],
                    "user_id": item[1],
                    "created_at": _marker_datetime(item[2]),
                    "updated_at": _marker_datetime(item[3]),
                }
                for item in sorted(items)
            ]
            for key, items in values.items()
        }
        bind.execute(
            agents.update()
            .where(agents.c.id == agent_id)
            .values(published_snapshot=updated)
        )


def _marker_datetime(value: Any) -> str:
    parsed = _json_datetime(value)
    if parsed is None:
        raise RuntimeError("Agent publication migration marker has invalid timestamp.")
    return parsed.isoformat()


def _migrated_tool_call_status(status: str, approval: str) -> str:
    if status != "pending":
        return status
    return "awaiting_approval" if approval == "each_call" else "queued"


def _migrated_invocation_state(
    call: Mapping[str, Any],
    deadline_base: datetime,
    approval: str,
) -> dict[str, Any]:
    status = _migrated_tool_call_status(call["status"], approval)
    terminal = status in {"succeeded", "failed", "rejected", "uncertain"}
    approved_by = call["approved_by_user_id"]
    approved_at = call["approved_at"]
    if approved_by is None or approved_at is None:
        approved_by = None
        approved_at = None
    result_data = _json_value(call["result_output"], None)
    if result_data is None and call["result_content"]:
        result_data = call["result_content"]
    return {
        "deadline_at": deadline_base.isoformat(),
        "status": status,
        "attempts": 1 if call["started_at"] is not None else 0,
        "max_attempts": 3,
        "approved_by_user_id": approved_by,
        "approved_at": approved_at,
        "worker_task_id": None,
        "lease_expires_at": None,
        "result_data": result_data,
        "result_summary": call["result_summary"] or "",
        "outcome": "uncertain" if status == "uncertain" else "confirmed" if terminal else None,
        "error_code": "legacy_tool_call_failed" if call["result_is_error"] else None,
        "error_message": call["last_error"],
        "usage": {},
        "started_at": call["started_at"],
        "finished_at": call["finished_at"],
        "created_at": call["created_at"],
        "updated_at": call["updated_at"],
    }


def _migrated_invocation_state_matches(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> bool:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if key in {"result_data", "usage"}:
            actual_value = _json_value(actual_value, None)
        if actual_value != expected_value:
            return False
    return True


def _migrate_agent_tool_calls(
    bind: sa.Connection,
    invocation_table: sa.Table,
    run: Mapping[str, Any],
    tools: list[dict[str, Any]],
    calls: list[Mapping[str, Any]],
) -> None:
    by_function_name = {item["function_name"]: item for item in tools}
    for call in calls:
        if call["tool_kind"] != "mcp":
            continue
        if call["status"] == "running":
            raise RuntimeError(
                "Drain running Agent Tool calls before applying this migration."
            )
        snapshot = by_function_name.get(call["tool_name"])
        if snapshot is None or call["definition_hash"] != snapshot["definition_hash"]:
            raise RuntimeError(
                "Legacy Agent Tool call does not match its immutable Tool version."
            )
        expected_approval = {
            "read_only": "auto",
            "approval_required": "each_call",
        }.get(call["policy_mode"])
        if expected_approval is None or snapshot["approval"] != expected_approval:
            raise RuntimeError(
                "Legacy Agent Tool call policy cannot be migrated without drift."
            )
        if run["access_source"] in {"public", "api"} and (
            snapshot["approval"] != "auto"
            or snapshot["effect"] not in {"pure", "external_read"}
        ):
            raise RuntimeError(
                "Drain unsafe external Agent Tool calls before applying this migration."
            )

        invocation_id = f"{call['turn']}:{call['call_id']}"
        if len(invocation_id) > 255:
            raise RuntimeError("Legacy Agent Tool call identity is too long.")
        identity = f"agent:{run['id']}:{invocation_id}"
        arguments = _json_value(call["arguments"], {})
        if not isinstance(arguments, Mapping):
            raise RuntimeError("Legacy Agent Tool arguments are invalid.")
        arguments = dict(arguments)
        arguments_hash = hashlib.sha256(
            json.dumps(
                arguments,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        deadline_base = call["updated_at"] or run["updated_at"]
        state = _migrated_invocation_state(
            call,
            deadline_base,
            snapshot["approval"],
        )
        bind.execute(
            invocation_table.insert().values(
                id=_stable_id(f"agent-tool-invocation:{call['id']}"),
                workspace_id=run["workspace_id"],
                origin="agent",
                root_run_id=run["id"],
                run_id=run["id"],
                invocation_id=invocation_id,
                execution_user_id=run["execution_user_id"],
                access_source=run["access_source"],
                tool_id=snapshot["tool_id"],
                tool_version_id=snapshot["version_id"],
                policy_snapshot={
                    "tool_snapshot": snapshot,
                    "deadline_at": state["deadline_at"],
                },
                arguments=arguments,
                arguments_hash=arguments_hash,
                idempotency_key=hashlib.sha256(identity.encode()).hexdigest(),
                **{key: value for key, value in state.items() if key != "deadline_at"},
            )
        )


def _remove_migrated_agent_tool_invocations(bind: sa.Connection) -> None:
    agent_tool_calls = sa.table(
        "agent_tool_calls",
        sa.column("id", sa.String(36)),
        sa.column("tool_kind", sa.String(30)),
    )
    tool_invocations = sa.table(
        "tool_invocations",
        sa.column("id", sa.String(36)),
    )
    invocation_ids = [
        _stable_id(f"agent-tool-invocation:{call_id}")
        for call_id in bind.execute(
            sa.select(agent_tool_calls.c.id).where(
                agent_tool_calls.c.tool_kind == "mcp"
            )
        ).scalars()
    ]
    for offset in range(0, len(invocation_ids), 1000):
        bind.execute(
            tool_invocations.delete().where(
                tool_invocations.c.id.in_(invocation_ids[offset : offset + 1000])
            )
        )


def _assert_downgrade_safe(bind: sa.Connection) -> None:
    agents = sa.table(
        "agents",
        sa.column("id", sa.String(36)),
        sa.column("app_type", sa.String(20)),
        sa.column("published_snapshot", sa.JSON()),
    )
    versions = sa.table(
        "agent_publication_versions",
        sa.column("id", sa.String(36)),
        sa.column("agent_id", sa.String(36)),
        sa.column("version_number", sa.Integer()),
        sa.column("resource_snapshot", sa.JSON()),
    )
    calls = sa.table(
        "agent_tool_calls",
        sa.column("id", sa.String(36)),
        sa.column("run_id", sa.String(36)),
        sa.column("turn", sa.Integer()),
        sa.column("call_id", sa.String(255)),
        sa.column("tool_name", sa.String(255)),
        sa.column("tool_kind", sa.String(30)),
        sa.column("arguments", sa.JSON()),
        sa.column("definition_hash", sa.String(64)),
        sa.column("policy_mode", sa.String(30)),
        sa.column("status", sa.String(30)),
        sa.column("approved_by_user_id", sa.String(36)),
        sa.column("approved_at", sa.DateTime(timezone=True)),
        sa.column("result_content", sa.Text()),
        sa.column("result_summary", sa.Text()),
        sa.column("result_output", sa.JSON()),
        sa.column("result_is_error", sa.Boolean()),
        sa.column("last_error", sa.Text()),
        sa.column("started_at", sa.DateTime(timezone=True)),
        sa.column("finished_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    invocations = sa.table(
        "tool_invocations",
        sa.column("id", sa.String(36)),
        sa.column("origin", sa.String(20)),
        sa.column("root_run_id", sa.String(36)),
        sa.column("run_id", sa.String(36)),
        sa.column("invocation_id", sa.String(255)),
        sa.column("policy_snapshot", sa.JSON()),
        sa.column("arguments", sa.JSON()),
        sa.column("arguments_hash", sa.String(64)),
        sa.column("idempotency_key", sa.String(255)),
        sa.column("status", sa.String(30)),
        sa.column("attempts", sa.Integer()),
        sa.column("max_attempts", sa.Integer()),
        sa.column("approved_by_user_id", sa.String(36)),
        sa.column("approved_at", sa.DateTime(timezone=True)),
        sa.column("worker_task_id", sa.String(255)),
        sa.column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.column("result_data", sa.JSON()),
        sa.column("result_summary", sa.Text()),
        sa.column("outcome", sa.String(20)),
        sa.column("error_code", sa.String(100)),
        sa.column("error_message", sa.Text()),
        sa.column("usage", sa.JSON()),
        sa.column("started_at", sa.DateTime(timezone=True)),
        sa.column("finished_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    runs = sa.table(
        "agent_runs",
        sa.column("id", sa.String(36)),
        sa.column("status", sa.String(20)),
        sa.column("configuration_source", sa.String(20)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    bindings = sa.table(
        "application_tool_bindings",
        sa.column("application_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("tool_version_id", sa.String(36)),
    )
    legacy_bindings = sa.table(
        "agent_mcp_tools",
        sa.column("agent_id", sa.String(36)),
        sa.column("mcp_server_id", sa.String(36)),
        sa.column("tool_name", sa.String(255)),
    )
    tools = sa.table(
        "tools",
        sa.column("id", sa.String(36)),
        sa.column("source_id", sa.String(36)),
        sa.column("current_version_id", sa.String(36)),
    )
    tool_versions = sa.table(
        "tool_versions",
        sa.column("id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("execution_spec", sa.JSON()),
    )
    sources = sa.table(
        "tool_sources",
        sa.column("id", sa.String(36)),
        sa.column("kind", sa.String(20)),
    )

    agent_rows = {
        row["id"]: row
        for row in bind.execute(
            sa.select(agents).where(agents.c.app_type == "agent")
        ).mappings()
    }
    publication_rows = list(bind.execute(sa.select(versions)).mappings())
    if any(
        row["version_number"] != 1
        or row["id"] != _stable_id(f"agent-publication:{row['agent_id']}:1")
        for row in publication_rows
    ):
        raise RuntimeError(
            "Cannot downgrade after canonical Agent publication writes."
        )

    run_rows = {
        row["id"]: row for row in bind.execute(sa.select(runs)).mappings()
    }
    call_rows = {
        _stable_id(f"agent-tool-invocation:{row['id']}"): row
        for row in bind.execute(
            sa.select(calls).where(calls.c.tool_kind == "mcp")
        ).mappings()
        if run_rows.get(row["run_id"], {}).get("configuration_source")
        in {"draft", "published"}
    }
    invocation_rows = {
        row["id"]: row
        for row in bind.execute(
            sa.select(invocations).where(invocations.c.origin == "agent")
        ).mappings()
    }
    if set(invocation_rows) != set(call_rows):
        raise RuntimeError("Cannot downgrade after canonical Agent Tool invocations.")
    for invocation_id, call in call_rows.items():
        invocation = invocation_rows[invocation_id]
        policy_snapshot = _json_value(invocation["policy_snapshot"], {})
        snapshot = (
            policy_snapshot.get("tool_snapshot", {})
            if isinstance(policy_snapshot, Mapping)
            else {}
        )
        expected_approval = {
            "read_only": "auto",
            "approval_required": "each_call",
        }.get(call["policy_mode"])
        run = run_rows[call["run_id"]]
        expected_invocation_id = f"{call['turn']}:{call['call_id']}"
        arguments = _json_value(call["arguments"], {})
        arguments_hash = hashlib.sha256(
            json.dumps(
                arguments,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        identity = f"agent:{call['run_id']}:{expected_invocation_id}"
        actual_state = {
            key: invocation[key]
            for key in (
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
            )
        }
        actual_state["deadline_at"] = (
            policy_snapshot.get("deadline_at")
            if isinstance(policy_snapshot, Mapping)
            else None
        )
        if (
            expected_approval is None
            or not isinstance(snapshot, Mapping)
            or snapshot.get("approval") != expected_approval
            or snapshot.get("definition_hash") != call["definition_hash"]
            or snapshot.get("function_name") != call["tool_name"]
            or invocation["root_run_id"] != call["run_id"]
            or invocation["run_id"] != call["run_id"]
            or invocation["invocation_id"] != expected_invocation_id
            or _json_value(invocation["arguments"], {}) != arguments
            or invocation["arguments_hash"] != arguments_hash
            or invocation["idempotency_key"]
            != hashlib.sha256(identity.encode()).hexdigest()
            or not _migrated_invocation_state_matches(
                _migrated_invocation_state(
                    call,
                    call["updated_at"] or run["updated_at"],
                    expected_approval,
                ),
                actual_state,
            )
        ):
            raise RuntimeError(
                "Cannot downgrade after a migrated Agent Tool invocation changed."
            )

    agent_ids = set(agent_rows)
    legacy_refs = {
        (row["agent_id"], row["mcp_server_id"], row["tool_name"])
        for row in bind.execute(sa.select(legacy_bindings)).mappings()
        if row["agent_id"] in agent_ids
    }
    version_rows = (
        list(
            bind.execute(
                sa.select(
                    bindings.c.application_id,
                    bindings.c.tool_id,
                    bindings.c.tool_version_id,
                    tools.c.current_version_id,
                    sources.c.kind,
                    tool_versions.c.execution_spec,
                )
                .select_from(
                    bindings.join(tools, tools.c.id == bindings.c.tool_id)
                    .join(sources, sources.c.id == tools.c.source_id)
                    .join(
                        tool_versions,
                        sa.and_(
                            tool_versions.c.id == bindings.c.tool_version_id,
                            tool_versions.c.tool_id == bindings.c.tool_id,
                        ),
                    )
                )
                .where(bindings.c.application_id.in_(agent_ids))
            ).mappings()
        )
        if agent_ids
        else []
    )
    canonical_refs: set[tuple[str, str, str]] = set()
    for row in version_rows:
        execution_spec = _json_value(row["execution_spec"], {})
        server_id = (
            execution_spec.get("server_id")
            if isinstance(execution_spec, Mapping)
            else None
        )
        if not server_id and isinstance(execution_spec, Mapping):
            server_id = execution_spec.get("legacy_server_id")
        tool_name = (
            execution_spec.get("tool_name")
            if isinstance(execution_spec, Mapping)
            else None
        )
        if (
            row["kind"] != "mcp"
            or row["tool_version_id"] != row["current_version_id"]
            or not isinstance(server_id, str)
            or not isinstance(tool_name, str)
        ):
            raise RuntimeError(
                "Cannot downgrade Agent bindings that legacy MCP cannot represent."
            )
        canonical_refs.add((row["application_id"], server_id, tool_name))
    if canonical_refs != legacy_refs:
        raise RuntimeError(
            "Cannot downgrade after canonical Agent binding writes."
        )

    current_versions = {
        row["id"]: row["current_version_id"]
        for row in bind.execute(sa.select(tools)).mappings()
    }
    legacy_by_agent: dict[str, set[tuple[str, str]]] = {}
    for agent_id, server_id, tool_name in legacy_refs:
        legacy_by_agent.setdefault(agent_id, set()).add((server_id, tool_name))
    for row in publication_rows:
        resources = _json_value(row["resource_snapshot"], {})
        snapshots = (
            resources.get("tools", []) if isinstance(resources, Mapping) else None
        )
        if not isinstance(snapshots, list):
            raise RuntimeError("Cannot downgrade invalid Agent publications.")
        refs: set[tuple[str, str]] = set()
        for snapshot in snapshots:
            if not isinstance(snapshot, Mapping):
                raise RuntimeError("Cannot downgrade invalid Agent publications.")
            execution_spec = snapshot.get("execution_spec", {})
            if not isinstance(execution_spec, Mapping):
                raise RuntimeError("Cannot downgrade invalid Agent publications.")
            server_id = execution_spec.get("server_id") or execution_spec.get(
                "legacy_server_id"
            )
            tool_name = execution_spec.get("tool_name")
            if (
                snapshot.get("kind") != "mcp"
                or current_versions.get(snapshot.get("tool_id")) != snapshot.get("version_id")
                or not isinstance(server_id, str)
                or not isinstance(tool_name, str)
            ):
                raise RuntimeError(
                    "Cannot downgrade Agent publications that legacy MCP cannot represent."
                )
            refs.add((server_id, tool_name))
        agent = agent_rows.get(row["agent_id"])
        if agent is None:
            raise RuntimeError("Cannot downgrade invalid Agent publications.")
        legacy_snapshot = _json_value(agent["published_snapshot"], {})
        expected = (
            set(_mcp_references(legacy_snapshot.get("mcp_tools")))
            if isinstance(legacy_snapshot, Mapping)
            and agent["published_snapshot"] is not None
            else legacy_by_agent.get(row["agent_id"], set())
        )
        if refs != expected:
            raise RuntimeError(
                "Cannot downgrade after canonical Agent publication writes."
            )


def _json_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _restore_migration_grants(bind: sa.Connection) -> None:
    agents = sa.table(
        "agents",
        sa.column("published_snapshot", sa.JSON()),
    )
    permissions = sa.table(
        "resource_permissions",
        sa.column("id", sa.String(36)),
        sa.column("user_id", sa.String(36)),
        sa.column("permission", sa.String(20)),
        sa.column("created_by_user_id", sa.String(36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    grants: dict[str, dict[str, Any]] = {}
    for value in bind.execute(sa.select(agents.c.published_snapshot)).scalars():
        snapshot = _json_value(value, {})
        marker = (
            snapshot.get(_MIGRATION_MARKER, {})
            if isinstance(snapshot, Mapping)
            else {}
        )
        if not isinstance(marker, Mapping):
            continue
        for item in marker.get("inserted_use_grants", []):
            if isinstance(item, Mapping) and isinstance(item.get("id"), str):
                grants.setdefault(item["id"], item)
    for permission_id, expected in grants.items():
        row = bind.execute(
            sa.select(permissions).where(permissions.c.id == permission_id)
        ).mappings().first()
        if row is None:
            # Already removed by the user after the migration.
            continue
        if (
            row["permission"] != "use"
            or row["user_id"] != expected.get("user_id")
            or row["created_by_user_id"] != expected.get("user_id")
            or row["created_at"] != _json_datetime(expected.get("created_at"))
            or row["updated_at"] != _json_datetime(expected.get("updated_at"))
        ):
            # The grant changed after migration; keep the user's change.
            continue
        bind.execute(permissions.delete().where(permissions.c.id == permission_id))


def _restore_legacy_agent_published_snapshots(bind: sa.Connection) -> None:
    agents = sa.table(
        "agents",
        sa.column("id", sa.String(36)),
        sa.column("published_snapshot", sa.JSON()),
    )
    versions = sa.table(
        "agent_publication_versions",
        sa.column("agent_id", sa.String(36)),
        sa.column("configuration_snapshot", sa.JSON()),
        sa.column("resource_snapshot", sa.JSON()),
    )
    for row in bind.execute(sa.select(versions)).mappings():
        configuration = _json_value(row["configuration_snapshot"], {})
        resources = _json_value(row["resource_snapshot"], {})
        if not isinstance(configuration, Mapping) or not isinstance(resources, Mapping):
            raise RuntimeError("Cannot downgrade invalid Agent publications.")
        bind.execute(
            agents.update()
            .where(agents.c.id == row["agent_id"])
            .values(
                published_snapshot=_legacy_publication_snapshot(
                    configuration,
                    resources,
                )
            )
        )


def _backfill(bind: sa.Connection, versions_table: sa.Table) -> None:
    agents = sa.table(
        "agents",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("name", sa.String(120)),
        sa.column("app_type", sa.String(20)),
        sa.column("description", sa.Text()),
        sa.column("interaction_config", sa.JSON()),
        sa.column("instructions", sa.Text()),
        sa.column("model_id", sa.String(36)),
        sa.column("knowledge_query_mode", sa.String(20)),
        sa.column("published", sa.Boolean()),
        sa.column("published_snapshot", sa.JSON()),
        sa.column("published_by_user_id", sa.String(36)),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("created_by_user_id", sa.String(36)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("current_published_version_id", sa.String(36)),
    )
    runs = sa.table(
        "agent_runs",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("agent_id", sa.String(36)),
        sa.column("execution_user_id", sa.String(36)),
        sa.column("access_source", sa.String(20)),
        sa.column("instructions", sa.Text()),
        sa.column("knowledge_base_ids", sa.JSON()),
        sa.column("knowledge_query_mode", sa.String(20)),
        sa.column("mcp_tools", sa.JSON()),
        sa.column("model_id", sa.String(36)),
        sa.column("status", sa.String(20)),
        sa.column("snapshot_schema_version", sa.Integer()),
        sa.column("configuration_source", sa.String(20)),
        sa.column("agent_publication_version_id", sa.String(36)),
        sa.column("application_snapshot", sa.JSON()),
        sa.column("application_snapshot_hash", sa.String(64)),
        sa.column("tool_snapshots", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    agent_tool_calls = sa.table(
        "agent_tool_calls",
        sa.column("id", sa.String(36)),
        sa.column("run_id", sa.String(36)),
        sa.column("turn", sa.Integer()),
        sa.column("call_id", sa.String(255)),
        sa.column("tool_name", sa.String(255)),
        sa.column("tool_kind", sa.String(30)),
        sa.column("arguments", sa.JSON()),
        sa.column("definition_hash", sa.String(64)),
        sa.column("policy_mode", sa.String(30)),
        sa.column("status", sa.String(30)),
        sa.column("approved_by_user_id", sa.String(36)),
        sa.column("approved_at", sa.DateTime(timezone=True)),
        sa.column("result_content", sa.Text()),
        sa.column("result_summary", sa.Text()),
        sa.column("result_output", sa.JSON()),
        sa.column("result_is_error", sa.Boolean()),
        sa.column("last_error", sa.Text()),
        sa.column("started_at", sa.DateTime(timezone=True)),
        sa.column("finished_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    tool_invocations = sa.table(
        "tool_invocations",
        sa.column("id", sa.String(36)),
        sa.column("workspace_id", sa.String(36)),
        sa.column("origin", sa.String(20)),
        sa.column("root_run_id", sa.String(36)),
        sa.column("run_id", sa.String(36)),
        sa.column("invocation_id", sa.String(255)),
        sa.column("execution_user_id", sa.String(36)),
        sa.column("access_source", sa.String(20)),
        sa.column("tool_id", sa.String(36)),
        sa.column("tool_version_id", sa.String(36)),
        sa.column("policy_snapshot", sa.JSON()),
        sa.column("arguments", sa.JSON()),
        sa.column("arguments_hash", sa.String(64)),
        sa.column("idempotency_key", sa.String(255)),
        sa.column("status", sa.String(30)),
        sa.column("attempts", sa.Integer()),
        sa.column("max_attempts", sa.Integer()),
        sa.column("approved_by_user_id", sa.String(36)),
        sa.column("approved_at", sa.DateTime(timezone=True)),
        sa.column("worker_task_id", sa.String(255)),
        sa.column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.column("result_data", sa.JSON()),
        sa.column("result_summary", sa.Text()),
        sa.column("outcome", sa.String(20)),
        sa.column("error_code", sa.String(100)),
        sa.column("error_message", sa.Text()),
        sa.column("usage", sa.JSON()),
        sa.column("started_at", sa.DateTime(timezone=True)),
        sa.column("finished_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    knowledge_bindings = sa.table(
        "agent_knowledge_bases",
        sa.column("agent_id", sa.String(36)),
        sa.column("knowledge_base_id", sa.String(36)),
    )
    application_bindings = sa.table(
        "application_tool_bindings",
        sa.column("workspace_id", sa.String(36)),
        sa.column("application_id", sa.String(36)),
        sa.column("tool_id", sa.String(36)),
        sa.column("tool_version_id", sa.String(36)),
        sa.column("bound_by_user_id", sa.String(36)),
    )
    (
        catalog,
        catalog_by_version,
        catalog_by_definition,
        tool_owners,
    ) = _tool_catalog(bind)
    binders = _binding_users(bind)
    fallback_grants: dict[tuple[str, str, str], dict[str, Any]] = {}
    knowledge_by_agent: dict[str, list[str]] = {}
    for binding in bind.execute(sa.select(knowledge_bindings)).mappings():
        knowledge_by_agent.setdefault(binding["agent_id"], []).append(
            binding["knowledge_base_id"]
        )
    tools_by_application: dict[str, list[dict[str, Any]]] = {}
    for binding in bind.execute(sa.select(application_bindings)).mappings():
        item = catalog_by_version.get(
            (binding["tool_id"], binding["tool_version_id"])
        )
        if item is None:
            raise RuntimeError("Current Agent Tool binding could not be materialized.")
        snapshot = dict(item)
        snapshot["bound_by_user_id"] = binding["bound_by_user_id"]
        tools_by_application.setdefault(binding["application_id"], []).append(snapshot)
    agent_rows = {
        row["id"]: row for row in bind.execute(sa.select(agents)).mappings()
    }
    publications: dict[str, dict[str, Any]] = {}
    calls_by_run: dict[str, list[Mapping[str, Any]]] = {}
    for call in bind.execute(sa.select(agent_tool_calls)).mappings():
        calls_by_run.setdefault(call["run_id"], []).append(call)

    for row in agent_rows.values():
        if row["app_type"] != "agent" or not row["published"]:
            continue
        has_legacy_snapshot = row["published_snapshot"] is not None
        legacy = _json_value(row["published_snapshot"], {})
        if not isinstance(legacy, Mapping):
            legacy = {}
        configuration = _configuration(row, legacy)
        if has_legacy_snapshot:
            knowledge_ids = _json_value(legacy.get("knowledge_base_ids"), [])
            if not isinstance(knowledge_ids, list):
                knowledge_ids = []
            tools = _tool_snapshots(
                row["workspace_id"],
                row["id"],
                row["created_by_user_id"],
                _mcp_references(legacy.get("mcp_tools")),
                catalog,
                binders,
                fallback_grants,
                row["published_at"] or row["updated_at"] or row["created_at"],
            )
        else:
            knowledge_ids = knowledge_by_agent.get(row["id"], [])
            tools = sorted(
                tools_by_application.get(row["id"], []),
                key=lambda item: (item["tool_id"], item["version_id"]),
            )
        resources = {
            "knowledge_base_ids": sorted({str(item) for item in knowledge_ids}),
            "tools": tools,
        }
        version_id = _stable_id(f"agent-publication:{row['id']}:1")
        version = {
            "id": version_id,
            "workspace_id": row["workspace_id"],
            "agent_id": row["id"],
            "version_number": 1,
            "schema_version": 1,
            "configuration_snapshot": configuration,
            "resource_snapshot": resources,
            "configuration_hash": _canonical_hash(configuration, resources),
            "published_by_user_id": row["published_by_user_id"]
            or row["created_by_user_id"],
            "created_at": row["published_at"] or row["updated_at"] or row["created_at"],
        }
        bind.execute(versions_table.insert().values(**version))
        bind.execute(
            agents.update()
            .where(agents.c.id == row["id"])
            .values(
                current_published_version_id=version_id,
                published_snapshot=_legacy_publication_snapshot(
                    configuration,
                    resources,
                ),
            )
        )
        publications[row["id"]] = version

    for run in bind.execute(sa.select(runs)).mappings():
        agent = agent_rows[run["agent_id"]]
        run_configuration = {
            "name": agent["name"],
            "description": agent["description"] or "",
            "instructions": run["instructions"],
            "model_id": run["model_id"],
            "knowledge_query_mode": run["knowledge_query_mode"],
            "interaction_config": _interaction_config(agent["interaction_config"]),
        }
        knowledge_ids = _json_value(run["knowledge_base_ids"], [])
        if not isinstance(knowledge_ids, list):
            knowledge_ids = []
        references = _mcp_references(run["mcp_tools"])
        terminal = run["status"] in _TERMINAL_RUN_STATUSES
        tools = (
            []
            if terminal
            else _run_tool_snapshots(
                run["workspace_id"],
                run["agent_id"],
                agent["created_by_user_id"],
                references,
                calls_by_run.get(run["id"], []),
                catalog,
                catalog_by_definition,
                tools_by_application.get(run["agent_id"], []),
                binders,
                fallback_grants,
                agent["updated_at"] or agent["created_at"],
            )
        )
        resources = {
            "knowledge_base_ids": sorted({str(item) for item in knowledge_ids}),
            "tools": tools,
        }
        source = "legacy"
        version_id = None
        snapshot_configuration = run_configuration
        snapshot_resources = resources
        publication = publications.get(run["agent_id"])
        if run["status"] not in _TERMINAL_RUN_STATUSES and agent["app_type"] == "agent":
            if run["access_source"] == "console":
                source = "draft"
            elif publication is not None:
                published_configuration = publication["configuration_snapshot"]
                published_resources = publication["resource_snapshot"]
                published_refs = sorted(
                    (
                        str(
                            item.get("execution_spec", {}).get("server_id")
                            or item.get("execution_spec", {}).get("legacy_server_id")
                            or ""
                        ),
                        str(item.get("execution_spec", {}).get("tool_name") or ""),
                    )
                    for item in published_resources["tools"]
                )
                if (
                    run["instructions"] == published_configuration["instructions"]
                    and run["model_id"] == published_configuration["model_id"]
                    and run["knowledge_query_mode"]
                    == published_configuration["knowledge_query_mode"]
                    and resources["knowledge_base_ids"]
                    == published_resources["knowledge_base_ids"]
                    and references == published_refs
                ):
                    source = "published"
                    version_id = publication["id"]
                    snapshot_configuration = published_configuration
                    snapshot_resources = published_resources
        snapshot_hash = _canonical_hash(snapshot_configuration, snapshot_resources)
        bind.execute(
            runs.update()
            .where(runs.c.id == run["id"])
            .values(
                snapshot_schema_version=1,
                configuration_source=source,
                agent_publication_version_id=version_id,
                application_snapshot={
                    "schema_version": 1,
                    "configuration": snapshot_configuration,
                    "resources": snapshot_resources,
                },
                application_snapshot_hash=snapshot_hash,
                tool_snapshots=snapshot_resources["tools"],
            )
        )
        if source in {"draft", "published"}:
            _migrate_agent_tool_calls(
                bind,
                tool_invocations,
                run,
                snapshot_resources["tools"],
                calls_by_run.get(run["id"], []),
            )
    _record_grant_markers(
        bind,
        _backfill_snapshot_use_grants(bind, fallback_grants, tool_owners),
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE agents, agent_runs, agent_tool_calls, tool_invocations, "
                "application_tool_bindings, agent_mcp_tools, resource_permissions, "
                "audit_logs, tools, tool_versions, tool_policies, tool_sources, "
                "workspace_memberships, users IN ACCESS EXCLUSIVE MODE"
            )
        )
    _assert_agent_runs_drained(bind)
    versions = op.create_table(
        "agent_publication_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("configuration_snapshot", sa.JSON(), nullable=False),
        sa.Column("resource_snapshot", sa.JSON(), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("published_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_agent_publication_versions_number"
        ),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_agent_publication_versions_schema"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_publication_versions_agent_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "version_number",
            name="uq_agent_publication_versions_agent_number",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_agent_publication_versions_workspace_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "agent_id",
            "id",
            name="uq_agent_publication_versions_workspace_agent_id",
        ),
    )
    for column in ("workspace_id", "agent_id", "published_by_user_id"):
        op.create_index(
            op.f(f"ix_agent_publication_versions_{column}"),
            "agent_publication_versions",
            [column],
        )

    op.add_column(
        "agents",
        sa.Column("current_published_version_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        op.f("ix_agents_current_published_version_id"),
        "agents",
        ["current_published_version_id"],
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "snapshot_schema_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "configuration_source",
            sa.String(length=20),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("agent_publication_version_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("application_snapshot", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "application_snapshot_hash",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("tool_snapshots", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index(
        op.f("ix_agent_runs_agent_publication_version_id"),
        "agent_runs",
        ["agent_publication_version_id"],
    )

    _backfill(bind, versions)

    op.create_foreign_key(
        "fk_agents_current_publication_workspace",
        "agents",
        "agent_publication_versions",
        ["workspace_id", "id", "current_published_version_id"],
        ["workspace_id", "agent_id", "id"],
    )
    op.create_foreign_key(
        "fk_agent_runs_publication_workspace",
        "agent_runs",
        "agent_publication_versions",
        ["workspace_id", "agent_id", "agent_publication_version_id"],
        ["workspace_id", "agent_id", "id"],
    )
    op.create_check_constraint(
        "ck_agent_runs_configuration_source",
        "agent_runs",
        "configuration_source IN ('draft', 'published', 'legacy')",
    )
    op.create_check_constraint(
        "ck_agent_runs_snapshot_schema_version",
        "agent_runs",
        "snapshot_schema_version >= 1",
    )
    op.create_check_constraint(
        "ck_agent_runs_publication_source",
        "agent_runs",
        "(configuration_source = 'published' AND agent_publication_version_id IS NOT NULL) "
        "OR (configuration_source IN ('draft', 'legacy') "
        "AND agent_publication_version_id IS NULL)",
    )
    for column, column_type in (
        ("snapshot_schema_version", sa.Integer()),
        ("configuration_source", sa.String(length=20)),
        ("application_snapshot", sa.JSON()),
        ("application_snapshot_hash", sa.String(length=64)),
        ("tool_snapshots", sa.JSON()),
    ):
        op.alter_column(
            "agent_runs",
            column,
            existing_type=column_type,
            server_default=None,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE agents, agent_runs, agent_tool_calls, tool_invocations, "
                "agent_publication_versions, application_tool_bindings, "
                "agent_mcp_tools, resource_permissions, audit_logs, tools, "
                "tool_versions, tool_policies, tool_sources, workspace_memberships, "
                "users IN ACCESS EXCLUSIVE MODE"
            )
        )
    _assert_downgrade_safe(bind)
    _restore_migration_grants(bind)
    _restore_legacy_agent_published_snapshots(bind)
    _remove_migrated_agent_tool_invocations(bind)
    for name in (
        "ck_agent_runs_publication_source",
        "ck_agent_runs_snapshot_schema_version",
        "ck_agent_runs_configuration_source",
    ):
        op.drop_constraint(name, "agent_runs", type_="check")
    op.drop_constraint(
        "fk_agent_runs_publication_workspace", "agent_runs", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_agent_runs_agent_publication_version_id"), table_name="agent_runs"
    )
    for column in (
        "tool_snapshots",
        "application_snapshot_hash",
        "application_snapshot",
        "agent_publication_version_id",
        "configuration_source",
        "snapshot_schema_version",
    ):
        op.drop_column("agent_runs", column)

    op.drop_constraint(
        "fk_agents_current_publication_workspace", "agents", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_agents_current_published_version_id"), table_name="agents"
    )
    op.drop_column("agents", "current_published_version_id")
    op.drop_table("agent_publication_versions")
