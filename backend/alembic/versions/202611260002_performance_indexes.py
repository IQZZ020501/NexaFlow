"""Add composite and partial PostgreSQL indexes for hot runtime and log queries."""

import sqlalchemy as sa

from alembic import op

revision = "202611260002"
down_revision = "202611260001"
branch_labels = None
depends_on = None

ACTIVE_RUN_STATUS_CONDITION = (
    "status IN ('queued', 'planning', 'planned', 'running', "
    "'awaiting_approval', 'awaiting_input', 'awaiting_child', "
    "'queued_v2', 'running_v2', 'awaiting_approval_v2', "
    "'awaiting_input_v2', 'awaiting_child_v2')"
)


def upgrade():
    op.create_index(
        "ix_agent_run_events_run_id_id",
        "agent_run_events",
        ["run_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_agent_source_consumer_created",
        "agent_runs",
        ["agent_id", "access_source", "consumer_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_conversation_agent_created",
        "agent_runs",
        ["agent_id", "access_source", "consumer_id", "conversation_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_run_states_active_lease",
        "agent_run_states",
        ["status", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text(ACTIVE_RUN_STATUS_CONDITION),
        sqlite_where=sa.text(ACTIVE_RUN_STATUS_CONDITION),
    )
    op.create_index(
        "ix_audit_logs_workspace_created_id",
        "audit_logs",
        ["workspace_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_created_id",
        "audit_logs",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_system_logs_created_id",
        "system_logs",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_system_logs_level_created",
        "system_logs",
        ["level", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_tool_invocations_workspace_run_created",
        "tool_invocations",
        ["workspace_id", "run_id", "created_at", "id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_tool_invocations_workspace_run_created",
        table_name="tool_invocations",
    )
    op.drop_index("ix_system_logs_level_created", table_name="system_logs")
    op.drop_index("ix_system_logs_created_id", table_name="system_logs")
    op.drop_index("ix_audit_logs_created_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_workspace_created_id", table_name="audit_logs")
    op.drop_index(
        "ix_agent_run_states_active_lease",
        table_name="agent_run_states",
    )
    op.drop_index(
        "ix_agent_runs_conversation_agent_created",
        table_name="agent_runs",
    )
    op.drop_index(
        "ix_agent_runs_agent_source_consumer_created",
        table_name="agent_runs",
    )
    op.drop_index(
        "ix_agent_run_events_run_id_id",
        table_name="agent_run_events",
    )
