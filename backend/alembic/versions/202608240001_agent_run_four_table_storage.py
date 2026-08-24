"""Split Agent Run identity, state, snapshot, events, and tool calls."""

from collections.abc import Mapping, Sequence
from datetime import datetime
import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision: str = "202608240001"
down_revision: str | None = "202608210001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_STATUSES = (
    "queued",
    "planning",
    "planned",
    "running",
    "awaiting_approval",
    "awaiting_input",
    "awaiting_child",
    "queued_v2",
    "running_v2",
    "awaiting_approval_v2",
    "awaiting_input_v2",
    "awaiting_child_v2",
)
_INTERNAL_LEDGER = "agent_internal_v1"


def _json(value: object, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _arguments_hash(arguments: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            arguments,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _internal_idempotency_key(call: Mapping[str, object]) -> str:
    value = call.get("idempotency_key")
    if isinstance(value, str) and value:
        return value
    return hashlib.sha256(
        f"agent-internal:{call['run_id']}:{call['turn']}:{call['call_id']}".encode()
    ).hexdigest()


def _project_events(events: Sequence[object]) -> list[dict[str, object]]:
    projected: list[dict[str, object]] = []
    for stored in events:
        if not isinstance(stored, Mapping) or stored.get("type") != "process":
            continue
        event = stored.get("event")
        if not isinstance(event, Mapping):
            continue
        item = dict(event)
        call_id = item.get("call_id")
        for index, current in enumerate(projected):
            same = (
                current.get("call_id") == call_id
                if call_id
                else current.get("type") == item.get("type")
                and current.get("turn") == item.get("turn")
                and current.get("tool_name") == item.get("tool_name")
            )
            if same:
                projected[index] = item
                break
        else:
            projected.append(item)
    return [item for item in projected if item.get("status") != "running"]


def _create_split_tables() -> None:
    op.create_table(
        "agent_run_states",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("access_source", sa.String(20), nullable=False),
        sa.Column("consumer_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("worker_generation", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("worker_task_id", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("checkpoint_phase", sa.String(20), nullable=False),
        sa.Column("grounding_status", sa.String(20), nullable=False),
        sa.Column("grounding_meta", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("context_summary", sa.Text(), nullable=False),
        sa.Column("model_usage", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "run_id",
                "agent_id",
                "access_source",
                "consumer_id",
                "conversation_id",
            ],
            [
                "agent_runs.workspace_id",
                "agent_runs.id",
                "agent_runs.agent_id",
                "agent_runs.access_source",
                "agent_runs.consumer_id",
                "agent_runs.conversation_id",
            ],
            name="fk_agent_run_states_run_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id"),
        sa.CheckConstraint(
            "status IN ('queued', 'planning', 'planned', 'running', "
            "'awaiting_approval', 'awaiting_input', 'awaiting_child', "
            "'queued_v2', 'running_v2', 'awaiting_approval_v2', "
            "'awaiting_input_v2', 'awaiting_child_v2', 'succeeded', "
            "'failed', 'cancelled')",
            name="ck_agent_run_states_status",
        ),
        sa.CheckConstraint(
            "worker_generation IN ('legacy', 'unified')",
            name="ck_agent_run_states_generation",
        ),
        sa.CheckConstraint(
            "(worker_generation = 'unified' AND status IN "
            "('queued_v2', 'running_v2', 'awaiting_approval_v2', "
            "'awaiting_input_v2', 'awaiting_child_v2', 'succeeded', 'failed', "
            "'cancelled')) OR (worker_generation = 'legacy' AND status IN "
            "('queued', 'planning', 'planned', 'running', 'awaiting_approval', "
            "'awaiting_input', 'awaiting_child', 'succeeded', 'failed', "
            "'cancelled'))",
            name="ck_agent_run_states_worker_generation",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="ck_agent_run_states_attempts",
        ),
        sa.CheckConstraint(
            "state_version >= 1", name="ck_agent_run_states_version"
        ),
        sa.CheckConstraint(
            "lease_expires_at IS NULL OR worker_task_id IS NOT NULL",
            name="ck_agent_run_states_lease",
        ),
    )
    for column in (
        "workspace_id",
        "agent_id",
        "status",
        "worker_task_id",
        "lease_expires_at",
    ):
        op.create_index(
            f"ix_agent_run_states_{column}", "agent_run_states", [column]
        )
    op.create_index(
        "uq_agent_run_states_active_conversation",
        "agent_run_states",
        [
            "workspace_id",
            "agent_id",
            "access_source",
            "consumer_id",
            "conversation_id",
        ],
        unique=True,
        postgresql_where=sa.column("status").in_(_ACTIVE_STATUSES),
        sqlite_where=sa.column("status").in_(_ACTIVE_STATUSES),
    )

    op.create_table(
        "agent_run_snapshots",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("snapshot_schema_version", sa.Integer(), nullable=False),
        sa.Column("configuration_source", sa.String(20), nullable=False),
        sa.Column("agent_publication_version_id", sa.String(36), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("knowledge_base_ids", sa.JSON(), nullable=False),
        sa.Column("knowledge_query_mode", sa.String(20), nullable=False),
        sa.Column("mcp_tools", sa.JSON(), nullable=False),
        sa.Column("application_snapshot", sa.JSON(), nullable=False),
        sa.Column("application_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("tool_snapshots", sa.JSON(), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id", "agent_id"],
            ["agent_runs.workspace_id", "agent_runs.id", "agent_runs.agent_id"],
            name="fk_agent_run_snapshots_run_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id", "agent_publication_version_id"],
            [
                "agent_publication_versions.workspace_id",
                "agent_publication_versions.agent_id",
                "agent_publication_versions.id",
            ],
            name="fk_agent_run_snapshots_publication_workspace",
        ),
        sa.PrimaryKeyConstraint("run_id"),
        sa.CheckConstraint(
            "knowledge_query_mode IN ('required', 'agentic')",
            name="ck_agent_run_snapshots_knowledge_query_mode",
        ),
        sa.CheckConstraint(
            "configuration_source IN ('draft', 'published', 'legacy')",
            name="ck_agent_run_snapshots_configuration_source",
        ),
        sa.CheckConstraint(
            "snapshot_schema_version >= 1",
            name="ck_agent_run_snapshots_schema_version",
        ),
        sa.CheckConstraint(
            "(configuration_source = 'published' AND "
            "agent_publication_version_id IS NOT NULL) OR "
            "(configuration_source IN ('draft', 'legacy') AND "
            "agent_publication_version_id IS NULL)",
            name="ck_agent_run_snapshots_publication_source",
        ),
    )
    for column in ("workspace_id", "agent_id", "agent_publication_version_id"):
        op.create_index(
            f"ix_agent_run_snapshots_{column}", "agent_run_snapshots", [column]
        )


def _backfill_split_tables(bind: sa.Connection) -> None:
    bind.execute(
        sa.text(
            """
            INSERT INTO agent_run_states (
                run_id, workspace_id, agent_id, access_source, consumer_id,
                conversation_id, worker_generation, status, state_version,
                attempts, max_attempts, worker_task_id, lease_expires_at,
                checkpoint, checkpoint_phase, grounding_status, grounding_meta,
                plan, result, context_summary, model_usage, last_error,
                planned_at, started_at, finished_at, updated_at
            )
            SELECT
                id, workspace_id, agent_id, access_source, consumer_id,
                conversation_id,
                CASE WHEN configuration_source IN ('draft', 'published')
                    THEN 'unified' ELSE 'legacy' END,
                status, 1, attempts, max_attempts, worker_task_id,
                lease_expires_at, checkpoint, checkpoint_phase,
                grounding_status, grounding_meta, plan, result,
                context_summary, model_usage, last_error, planned_at,
                started_at, finished_at, updated_at
            FROM agent_runs
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO agent_run_snapshots (
                run_id, workspace_id, agent_id, snapshot_schema_version,
                configuration_source, agent_publication_version_id,
                instructions, knowledge_base_ids, knowledge_query_mode,
                mcp_tools, application_snapshot, application_snapshot_hash,
                tool_snapshots, model_id, model_name, created_at
            )
            SELECT
                id, workspace_id, agent_id, snapshot_schema_version,
                configuration_source, agent_publication_version_id,
                instructions, knowledge_base_ids, knowledge_query_mode,
                mcp_tools, application_snapshot, application_snapshot_hash,
                tool_snapshots, model_id, model_name, created_at
            FROM agent_runs
            """
        )
    )


def _backfill_run_events(bind: sa.Connection) -> None:
    metadata = sa.MetaData()
    runs = sa.Table("agent_runs", metadata, autoload_with=bind)
    event_rows = sa.Table("agent_run_events", metadata, autoload_with=bind)
    existing: dict[str, list[object]] = {}
    for row in bind.execute(
        sa.select(event_rows.c.run_id, event_rows.c.event)
    ).mappings():
        existing.setdefault(row["run_id"], []).append(_json(row["event"], {}))
    for run in bind.execute(sa.select(runs)).mappings():
        projection = _json(run["events"], [])
        if not isinstance(projection, list):
            continue
        if _project_events(existing.get(run["id"], [])) == projection:
            continue
        for event in projection:
            if isinstance(event, Mapping):
                bind.execute(
                    event_rows.insert().values(
                        workspace_id=run["workspace_id"],
                        run_id=run["id"],
                        event={"type": "process", "event": dict(event)},
                        created_at=run["updated_at"],
                    )
                )


def _migrate_tool_calls(bind: sa.Connection) -> None:
    metadata = sa.MetaData()
    calls = sa.Table("agent_tool_calls", metadata, autoload_with=bind)
    runs = sa.Table("agent_runs", metadata, autoload_with=bind)
    invocations = sa.Table("tool_invocations", metadata, autoload_with=bind)
    run_rows = {
        row["id"]: row for row in bind.execute(sa.select(runs)).mappings()
    }
    for call in bind.execute(sa.select(calls)).mappings():
        run = run_rows[call["run_id"]]
        invocation_id = f"{call['turn']}:{call['call_id']}"
        existing = bind.execute(
            sa.select(invocations).where(
                invocations.c.workspace_id == call["workspace_id"],
                invocations.c.origin == "agent",
                invocations.c.run_id == call["run_id"],
                invocations.c.invocation_id == invocation_id,
            )
        ).mappings().first()
        effect = (
            "pure"
            if call["tool_kind"] == "knowledge"
            else "external_write"
            if call["approval_required"]
            else "external_read"
        )
        policy = dict(_json(existing["policy_snapshot"], {}) if existing else {})
        policy.update(
            {
                "ledger_kind": _INTERNAL_LEDGER,
                "internal_tool": {
                    "turn": call["turn"],
                    "call_id": call["call_id"],
                    "tool_name": call["tool_name"],
                    "tool_kind": call["tool_kind"],
                    "server_name": call["server_name"],
                    "definition_hash": call["definition_hash"],
                    "policy_mode": call["policy_mode"],
                    "approval_required": bool(call["approval_required"]),
                    "effect": effect,
                },
            }
        )
        arguments = _json(call["arguments"], {})
        if not isinstance(arguments, Mapping):
            arguments = {}
        arguments = dict(arguments)
        argument_hash = call["arguments_hash"]
        if not isinstance(argument_hash, str) or len(argument_hash) != 64:
            argument_hash = _arguments_hash(arguments)
        status = "queued" if call["status"] == "pending" else call["status"]
        approved_by = call["approved_by_user_id"]
        approved_at = call["approved_at"]
        if approved_by is None or approved_at is None:
            approved_by = approved_at = None
        values = {
            "policy_snapshot": policy,
            "arguments": arguments,
            "arguments_hash": argument_hash,
            "status": status,
            "approved_by_user_id": approved_by,
            "approved_at": approved_at,
            "worker_task_id": call["worker_task_id"],
            "lease_expires_at": (
                call["lease_expires_at"] if call["worker_task_id"] else None
            ),
            "result_data": {
                "content": call["result_content"],
                "output": _json(call["result_output"], None),
                "is_error": bool(call["result_is_error"]),
                "evidence_ids": _json(call["result_evidence_ids"], []),
            },
            "result_summary": call["result_summary"],
            "outcome": (
                "uncertain"
                if status == "uncertain"
                else "confirmed"
                if status in {"succeeded", "failed", "rejected", "cancelled"}
                else None
            ),
            "error_code": "agent_tool_error" if call["last_error"] else None,
            "error_message": call["last_error"],
            "started_at": call["started_at"],
            "finished_at": call["finished_at"],
            "updated_at": call["updated_at"],
        }
        if existing:
            bind.execute(
                invocations.update()
                .where(invocations.c.id == existing["id"])
                .values(**values)
            )
            continue
        idempotency_key = _internal_idempotency_key(call)
        if bind.execute(
            sa.select(invocations.c.id).where(
                invocations.c.workspace_id == call["workspace_id"],
                invocations.c.idempotency_key == idempotency_key,
            )
        ).first():
            idempotency_key = hashlib.sha256(
                f"agent-internal:{call['run_id']}:{call['turn']}:{call['call_id']}".encode()
            ).hexdigest()
        bind.execute(
            invocations.insert().values(
                id=call["id"],
                workspace_id=call["workspace_id"],
                origin="agent",
                root_run_id=run["root_run_id"],
                run_id=call["run_id"],
                invocation_id=invocation_id,
                execution_user_id=run["execution_user_id"],
                access_source=run["access_source"],
                tool_id=None,
                tool_version_id=None,
                idempotency_key=idempotency_key,
                attempts=1 if status == "running" else 0,
                max_attempts=3,
                usage={},
                created_at=call["created_at"],
                **values,
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE agent_runs, agent_tool_calls, tool_invocations, "
                "agent_run_events IN ACCESS EXCLUSIVE MODE"
            )
        )
    with op.batch_alter_table("agent_runs") as batch:
        batch.create_unique_constraint(
            "uq_agent_runs_workspace_agent_id", ["workspace_id", "id", "agent_id"]
        )
        batch.create_unique_constraint(
            "uq_agent_runs_state_identity",
            [
                "workspace_id",
                "id",
                "agent_id",
                "access_source",
                "consumer_id",
                "conversation_id",
            ],
        )
    with op.batch_alter_table("tool_invocations") as batch:
        batch.alter_column("tool_id", existing_type=sa.String(36), nullable=True)
        batch.alter_column(
            "tool_version_id", existing_type=sa.String(36), nullable=True
        )
        batch.create_check_constraint(
            "ck_tool_invocations_tool_version_pair",
            "(tool_id IS NULL AND tool_version_id IS NULL) OR "
            "(tool_id IS NOT NULL AND tool_version_id IS NOT NULL)",
        )
    _create_split_tables()
    _backfill_split_tables(bind)
    _backfill_run_events(bind)
    _migrate_tool_calls(bind)
    op.drop_table("agent_tool_calls")

    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    for index in (
        "ix_agent_runs_status",
        "ix_agent_runs_worker_task_id",
        "ix_agent_runs_lease_expires_at",
        "ix_agent_runs_agent_publication_version_id",
    ):
        op.drop_index(index, table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("fk_agent_runs_publication_workspace", type_="foreignkey")
        for constraint in (
            "ck_agent_runs_status",
            "ck_agent_runs_knowledge_query_mode",
            "ck_agent_runs_configuration_source",
            "ck_agent_runs_snapshot_schema_version",
            "ck_agent_runs_publication_source",
            "ck_agent_runs_worker_generation",
        ):
            batch.drop_constraint(constraint, type_="check")
        for column in (
            "instructions",
            "knowledge_base_ids",
            "knowledge_query_mode",
            "mcp_tools",
            "snapshot_schema_version",
            "configuration_source",
            "agent_publication_version_id",
            "application_snapshot",
            "application_snapshot_hash",
            "tool_snapshots",
            "model_id",
            "model_name",
            "status",
            "attempts",
            "max_attempts",
            "worker_task_id",
            "lease_expires_at",
            "checkpoint",
            "checkpoint_phase",
            "grounding_status",
            "grounding_meta",
            "plan",
            "events",
            "result",
            "context_summary",
            "model_usage",
            "last_error",
            "planned_at",
            "started_at",
            "finished_at",
            "updated_at",
        ):
            batch.drop_column(column)


def _create_legacy_tool_calls() -> None:
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("tool_kind", sa.String(30), nullable=False),
        sa.Column("server_name", sa.String(255), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("policy_mode", sa.String(30), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_task_id", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_content", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.String(2000), nullable=False),
        sa.Column("result_output", sa.JSON(), nullable=True),
        sa.Column("result_is_error", sa.Boolean(), nullable=False),
        sa.Column("result_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_agent_tool_calls_run_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "turn", "call_id", name="uq_agent_tool_calls_run_turn_call"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'awaiting_approval', 'approved', 'running', "
            "'succeeded', 'failed', 'rejected', 'uncertain')",
            name="ck_agent_tool_calls_status",
        ),
    )
    for column in ("workspace_id", "run_id", "status"):
        op.create_index(
            f"ix_agent_tool_calls_{column}", "agent_tool_calls", [column]
        )


def _restore_legacy_tool_calls(bind: sa.Connection) -> None:
    metadata = sa.MetaData()
    invocations = sa.Table("tool_invocations", metadata, autoload_with=bind)
    calls = sa.Table("agent_tool_calls", metadata, autoload_with=bind)
    for row in bind.execute(sa.select(invocations)).mappings():
        policy = _json(row["policy_snapshot"], {})
        if not isinstance(policy, Mapping) or policy.get("ledger_kind") != _INTERNAL_LEDGER:
            continue
        metadata = policy.get("internal_tool", {})
        result = _json(row["result_data"], {})
        if not isinstance(metadata, Mapping):
            metadata = {}
        if not isinstance(result, Mapping):
            result = {}
        status = "pending" if row["status"] == "queued" else row["status"]
        if status == "cancelled":
            status = "failed"
        bind.execute(
            calls.insert().values(
                id=row["id"],
                workspace_id=row["workspace_id"],
                run_id=row["run_id"],
                turn=int(metadata.get("turn", 0)),
                call_id=str(metadata.get("call_id", row["invocation_id"])),
                tool_name=str(metadata.get("tool_name", "")),
                tool_kind=str(metadata.get("tool_kind", "unknown")),
                server_name=str(metadata.get("server_name", "")),
                arguments=_json(row["arguments"], {}),
                arguments_hash=row["arguments_hash"],
                definition_hash=str(metadata.get("definition_hash", "")),
                policy_mode=str(metadata.get("policy_mode", "")),
                idempotency_key=row["idempotency_key"],
                status=status,
                approval_required=bool(metadata.get("approval_required", False)),
                approved_by_user_id=row["approved_by_user_id"],
                approved_at=row["approved_at"],
                worker_task_id=row["worker_task_id"],
                lease_expires_at=row["lease_expires_at"],
                result_content=str(result.get("content", "")),
                result_summary=str(row["result_summary"] or "")[:2000],
                result_output=result.get("output"),
                result_is_error=bool(result.get("is_error", False)),
                result_evidence_ids=list(result.get("evidence_ids") or []),
                last_error=row["error_message"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
        if row["tool_id"] is None:
            bind.execute(invocations.delete().where(invocations.c.id == row["id"]))
        else:
            cleaned = dict(policy)
            cleaned.pop("ledger_kind", None)
            cleaned.pop("internal_tool", None)
            bind.execute(
                invocations.update()
                .where(invocations.c.id == row["id"])
                .values(policy_snapshot=cleaned)
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE agent_runs, agent_run_states, agent_run_snapshots, "
                "tool_invocations, agent_run_events IN ACCESS EXCLUSIVE MODE"
            )
        )
    legacy_columns = (
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("knowledge_base_ids", sa.JSON(), nullable=True),
        sa.Column("knowledge_query_mode", sa.String(20), nullable=True),
        sa.Column("mcp_tools", sa.JSON(), nullable=True),
        sa.Column("snapshot_schema_version", sa.Integer(), nullable=True),
        sa.Column("configuration_source", sa.String(20), nullable=True),
        sa.Column("agent_publication_version_id", sa.String(36), nullable=True),
        sa.Column("application_snapshot", sa.JSON(), nullable=True),
        sa.Column("application_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("tool_snapshots", sa.JSON(), nullable=True),
        sa.Column("model_id", sa.String(36), nullable=True),
        sa.Column("model_name", sa.String(160), nullable=True),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("worker_task_id", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint", sa.JSON(), nullable=True),
        sa.Column("checkpoint_phase", sa.String(20), nullable=True),
        sa.Column("grounding_status", sa.String(20), nullable=True),
        sa.Column("grounding_meta", sa.JSON(), nullable=True),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.Column("events", sa.JSON(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("model_usage", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table("agent_runs") as batch:
        for column in legacy_columns:
            batch.add_column(column)

    metadata = sa.MetaData()
    runs = sa.Table("agent_runs", metadata, autoload_with=bind)
    states = sa.Table("agent_run_states", metadata, autoload_with=bind)
    snapshots = sa.Table("agent_run_snapshots", metadata, autoload_with=bind)
    state_rows = {row["run_id"]: row for row in bind.execute(sa.select(states)).mappings()}
    snapshot_rows = {row["run_id"]: row for row in bind.execute(sa.select(snapshots)).mappings()}
    stored_events: dict[str, list[object]] = {}
    events = sa.Table("agent_run_events", metadata, autoload_with=bind)
    for row in bind.execute(sa.select(events)).mappings():
        stored_events.setdefault(row["run_id"], []).append(_json(row["event"], {}))
    for run_id, state in state_rows.items():
        snapshot = snapshot_rows[run_id]
        values = {name: state[name] for name in _RUN_STATE_NAMES if name != "run_id"}
        values.update({name: snapshot[name] for name in _RUN_SNAPSHOT_NAMES if name not in {"run_id", "created_at"}})
        values["events"] = _project_events(stored_events.get(run_id, []))
        bind.execute(runs.update().where(runs.c.id == run_id).values(**values))

    op.create_index(
        "uq_agent_runs_active_conversation",
        "agent_runs",
        ["workspace_id", "agent_id", "access_source", "consumer_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.column("status").in_(_ACTIVE_STATUSES),
        sqlite_where=sa.column("status").in_(_ACTIVE_STATUSES),
    )
    for column in ("status", "worker_task_id", "lease_expires_at", "agent_publication_version_id"):
        op.create_index(f"ix_agent_runs_{column}", "agent_runs", [column])
    with op.batch_alter_table("agent_runs") as batch:
        for column in legacy_columns:
            if column.name != "agent_publication_version_id":
                batch.alter_column(column.name, nullable=False if column.name in _RUN_REQUIRED_COLUMNS else True)
        batch.create_foreign_key(
            "fk_agent_runs_publication_workspace",
            "agent_publication_versions",
            ["workspace_id", "agent_id", "agent_publication_version_id"],
            ["workspace_id", "agent_id", "id"],
        )
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('queued', 'planning', 'planned', 'running', "
            "'awaiting_approval', 'awaiting_input', 'awaiting_child', "
            "'queued_v2', 'running_v2', 'awaiting_approval_v2', "
            "'awaiting_input_v2', 'awaiting_child_v2', 'succeeded', 'failed', 'cancelled')",
        )
        batch.create_check_constraint("ck_agent_runs_knowledge_query_mode", "knowledge_query_mode IN ('required', 'agentic')")
        batch.create_check_constraint("ck_agent_runs_configuration_source", "configuration_source IN ('draft', 'published', 'legacy')")
        batch.create_check_constraint("ck_agent_runs_snapshot_schema_version", "snapshot_schema_version >= 1")
        batch.create_check_constraint(
            "ck_agent_runs_publication_source",
            "(configuration_source = 'published' AND agent_publication_version_id IS NOT NULL) OR "
            "(configuration_source IN ('draft', 'legacy') AND agent_publication_version_id IS NULL)",
        )
        batch.create_check_constraint(
            "ck_agent_runs_worker_generation",
            "(configuration_source IN ('draft', 'published') AND status IN "
            "('queued_v2', 'running_v2', 'awaiting_approval_v2', 'awaiting_input_v2', "
            "'awaiting_child_v2', 'succeeded', 'failed', 'cancelled')) OR "
            "(configuration_source = 'legacy' AND status IN ('queued', 'planning', "
            "'planned', 'running', 'awaiting_approval', 'awaiting_input', "
            "'awaiting_child', 'succeeded', 'failed', 'cancelled'))",
        )

    _create_legacy_tool_calls()
    _restore_legacy_tool_calls(bind)
    with op.batch_alter_table("tool_invocations") as batch:
        batch.drop_constraint("ck_tool_invocations_tool_version_pair", type_="check")
        batch.alter_column("tool_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("tool_version_id", existing_type=sa.String(36), nullable=False)

    op.drop_table("agent_run_snapshots")
    op.drop_table("agent_run_states")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("uq_agent_runs_state_identity", type_="unique")
        batch.drop_constraint("uq_agent_runs_workspace_agent_id", type_="unique")


_RUN_STATE_NAMES = (
    "run_id", "status", "attempts", "max_attempts", "worker_task_id",
    "lease_expires_at", "checkpoint", "checkpoint_phase", "grounding_status",
    "grounding_meta", "plan", "result", "context_summary", "model_usage",
    "last_error", "planned_at", "started_at", "finished_at", "updated_at",
)
_RUN_SNAPSHOT_NAMES = (
    "run_id", "snapshot_schema_version", "configuration_source",
    "agent_publication_version_id", "instructions", "knowledge_base_ids",
    "knowledge_query_mode", "mcp_tools", "application_snapshot",
    "application_snapshot_hash", "tool_snapshots", "model_id", "model_name",
    "created_at",
)
_RUN_REQUIRED_COLUMNS = {
    "instructions", "knowledge_base_ids", "knowledge_query_mode", "mcp_tools",
    "snapshot_schema_version", "configuration_source", "application_snapshot",
    "application_snapshot_hash", "tool_snapshots", "model_id", "model_name",
    "status", "attempts", "max_attempts", "checkpoint", "checkpoint_phase",
    "grounding_status", "grounding_meta", "plan", "events", "result",
    "context_summary", "model_usage", "updated_at",
}
