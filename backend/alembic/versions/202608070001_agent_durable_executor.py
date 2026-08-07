"""durable agent executor, explicit knowledge policy, and MCP approvals

Revision ID: 202608070001
Revises: 202608060001
Create Date: 2026-08-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608070001"
down_revision: str | None = "202608060001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(
            sa.Column(
                "knowledge_query_mode",
                sa.String(length=20),
                nullable=True,
                server_default="required",
            )
        )
        batch.create_check_constraint(
            "ck_agents_knowledge_query_mode",
            "knowledge_query_mode IN ('required', 'agentic')",
        )
    op.execute(
        "UPDATE agents SET knowledge_query_mode = 'required' "
        "WHERE knowledge_query_mode IS NULL"
    )
    with op.batch_alter_table("agents") as batch:
        batch.alter_column("knowledge_query_mode", nullable=False)

    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.add_column(
            sa.Column(
                "knowledge_query_mode",
                sa.String(length=20),
                nullable=True,
                server_default="required",
            )
        )
        batch.add_column(
            sa.Column("attempts", sa.Integer(), nullable=True, server_default="0")
        )
        batch.add_column(
            sa.Column("max_attempts", sa.Integer(), nullable=True, server_default="3")
        )
        batch.add_column(sa.Column("worker_task_id", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("checkpoint", sa.JSON(), nullable=True, server_default="{}")
        )
        batch.add_column(
            sa.Column(
                "checkpoint_phase",
                sa.String(length=20),
                nullable=True,
                server_default="agent",
            )
        )
        batch.add_column(
            sa.Column(
                "trace_id",
                sa.String(length=36),
                nullable=True,
                server_default="",
            )
        )
        batch.create_unique_constraint("uq_agent_runs_workspace_id", ["workspace_id", "id"])
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('queued', 'planning', 'planned', 'running', 'awaiting_approval', 'succeeded', 'failed', 'cancelled')",
        )
        batch.create_check_constraint(
            "ck_agent_runs_knowledge_query_mode",
            "knowledge_query_mode IN ('required', 'agentic')",
        )
    op.execute(
        "UPDATE agent_runs SET knowledge_query_mode = 'required', attempts = 0, "
        "max_attempts = 3, checkpoint = '{}', checkpoint_phase = 'agent', trace_id = '' "
        "WHERE knowledge_query_mode IS NULL OR attempts IS NULL OR max_attempts IS NULL "
        "OR checkpoint IS NULL OR checkpoint_phase IS NULL OR trace_id IS NULL"
    )
    with op.batch_alter_table("agent_runs") as batch:
        batch.alter_column("knowledge_query_mode", nullable=False)
        batch.alter_column("attempts", nullable=False)
        batch.alter_column("max_attempts", nullable=False)
        batch.alter_column("checkpoint", nullable=False)
        batch.alter_column("checkpoint_phase", nullable=False)
        batch.alter_column("trace_id", nullable=False)
        batch.create_index("ix_agent_runs_worker_task_id", ["worker_task_id"])
        batch.create_index("ix_agent_runs_lease_expires_at", ["lease_expires_at"])

    op.create_table(
        "agent_run_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("event", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_agent_run_events_run_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_run_events_workspace_id", "agent_run_events", ["workspace_id"])
    op.create_index("ix_agent_run_events_run_id", "agent_run_events", ["run_id"])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("tool_kind", sa.String(length=30), nullable=False),
        sa.Column("server_name", sa.String(length=255), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_mode", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_task_id", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_content", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.String(length=2000), nullable=False),
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
            "run_id",
            "turn",
            "call_id",
            name="uq_agent_tool_calls_run_turn_call",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'awaiting_approval', 'approved', 'running', 'succeeded', 'failed', 'rejected', 'uncertain')",
            name="ck_agent_tool_calls_status",
        ),
    )
    op.create_index("ix_agent_tool_calls_workspace_id", "agent_tool_calls", ["workspace_id"])
    op.create_index("ix_agent_tool_calls_run_id", "agent_tool_calls", ["run_id"])
    op.create_index("ix_agent_tool_calls_status", "agent_tool_calls", ["status"])

    op.create_table(
        "mcp_tool_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("mcp_server_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=30), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "mcp_server_id"],
            ["mcp_servers.workspace_id", "mcp_servers.id"],
            name="fk_mcp_tool_policies_server_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "mcp_server_id",
            "tool_name",
            name="uq_mcp_tool_policies_tool",
        ),
        sa.CheckConstraint(
            "mode IN ('approval_required', 'read_only', 'disabled')",
            name="ck_mcp_tool_policies_mode",
        ),
    )
    op.create_index("ix_mcp_tool_policies_workspace_id", "mcp_tool_policies", ["workspace_id"])
    op.create_index("ix_mcp_tool_policies_mcp_server_id", "mcp_tool_policies", ["mcp_server_id"])


def downgrade() -> None:
    op.drop_table("mcp_tool_policies")
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_run_events")
    op.execute(
        "UPDATE agent_runs SET status = CASE "
        "WHEN status IN ('queued', 'awaiting_approval') THEN 'planning' "
        "WHEN status = 'cancelled' THEN 'failed' ELSE status END"
    )
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_index("ix_agent_runs_lease_expires_at")
        batch.drop_index("ix_agent_runs_worker_task_id")
        batch.drop_constraint("ck_agent_runs_knowledge_query_mode", type_="check")
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.drop_constraint("uq_agent_runs_workspace_id", type_="unique")
        for column in (
            "trace_id",
            "checkpoint_phase",
            "checkpoint",
            "lease_expires_at",
            "worker_task_id",
            "max_attempts",
            "attempts",
            "knowledge_query_mode",
        ):
            batch.drop_column(column)
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('planning', 'planned', 'running', 'succeeded', 'failed')",
        )
    with op.batch_alter_table("agents") as batch:
        batch.drop_constraint("ck_agents_knowledge_query_mode", type_="check")
        batch.drop_column("knowledge_query_mode")
