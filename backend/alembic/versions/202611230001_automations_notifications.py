"""Add automations, automation executions, user notifications, and automation run source."""

import sqlalchemy as sa

from alembic import op

revision = "202611230001"
down_revision = "202611220001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("target_app_id", sa.String(length=36), nullable=False),
        sa.Column("target_app_type", sa.String(length=20), nullable=False),
        sa.Column("publication_version_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_version_id", sa.String(length=36), nullable=True),
        sa.Column("target_version_number", sa.Integer(), nullable=False),
        sa.Column("approval_mode", sa.String(length=24), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("trigger_config", sa.JSON(), nullable=False),
        sa.Column("input_config", sa.JSON(), nullable=False),
        sa.Column("notification_config", sa.JSON(), nullable=False),
        sa.Column("webhook_hook_id", sa.String(length=64), nullable=True),
        sa.Column("webhook_secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("webhook_secret_hint", sa.String(length=32), nullable=True),
        sa.Column(
            "webhook_secret_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missed_run_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_app_type IN ('agent', 'workflow')",
            name="ck_automations_target_app_type",
        ),
        sa.CheckConstraint(
            "trigger_type IN ('once', 'daily', 'weekly', 'webhook')",
            name="ck_automations_trigger_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'completed')",
            name="ck_automations_status",
        ),
        sa.CheckConstraint(
            "approval_mode IN ('always_ask', 'ask_risky', 'full_access')",
            name="ck_automations_approval_mode",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["target_app_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["publication_version_id"],
            ["agent_publication_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"],
            ["workflow_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("webhook_hook_id"),
    )
    op.create_index("ix_automations_workspace_id", "automations", ["workspace_id"])
    op.create_index("ix_automations_owner_user_id", "automations", ["owner_user_id"])
    op.create_index("ix_automations_target_app_id", "automations", ["target_app_id"])
    op.create_index("ix_automations_next_run_at", "automations", ["next_run_at"])
    op.create_index("ix_automations_due", "automations", ["status", "next_run_at"])
    op.create_index(
        "ix_automations_workspace_owner",
        "automations",
        ["workspace_id", "owner_user_id", "created_at"],
    )

    op.create_table(
        "automation_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("automation_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("trigger_source", sa.String(length=20), nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("frozen_input", sa.JSON(), nullable=False),
        sa.Column("frozen_config", sa.JSON(), nullable=False),
        sa.Column("dispatch_status", sa.String(length=24), nullable=False),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("missed_count_before", sa.Integer(), nullable=False),
        sa.Column("last_reconciled_run_status", sa.Text(), nullable=True),
        sa.Column("notification_closed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "trigger_source IN ('schedule', 'webhook', 'manual')",
            name="ck_automation_executions_trigger_source",
        ),
        sa.CheckConstraint(
            "dispatch_status IN "
            "('queued', 'pending_dispatch', 'dispatched', 'skipped', 'rejected')",
            name="ck_automation_executions_dispatch_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"], ["automations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "automation_id",
            "dedup_key",
            name="uq_automation_executions_dedup",
        ),
        sa.UniqueConstraint("run_id", name="uq_automation_executions_run_id"),
    )
    op.create_index(
        "ix_automation_executions_workspace_id",
        "automation_executions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_automation_executions_automation_id",
        "automation_executions",
        ["automation_id"],
    )
    op.create_index(
        "ix_automation_executions_owner_user_id",
        "automation_executions",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_automation_executions_lookup",
        "automation_executions",
        ["automation_id", "created_at", "id"],
    )
    op.create_index(
        "ix_automation_executions_pending_dispatch",
        "automation_executions",
        ["dispatch_status", "created_at"],
    )
    op.create_index(
        "ix_automation_executions_unclosed_notifications",
        "automation_executions",
        ["notification_closed", "updated_at"],
    )

    op.create_table(
        "user_notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("automation_id", sa.String(length=36), nullable=True),
        sa.Column("execution_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN "
            "('succeeded', 'failed', 'cancelled', 'awaiting_approval', 'awaiting_input')",
            name="ck_user_notifications_event_type",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"], ["automations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["automation_executions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "dedup_key",
            name="uq_user_notifications_dedup",
        ),
    )
    op.create_index("ix_user_notifications_user_id", "user_notifications", ["user_id"])
    op.create_index(
        "ix_user_notifications_workspace_id", "user_notifications", ["workspace_id"]
    )
    op.create_index(
        "ix_user_notifications_user_inbox",
        "user_notifications",
        ["user_id", "workspace_id", "created_at", "id"],
    )
    op.create_index(
        "ix_user_notifications_unread",
        "user_notifications",
        ["user_id", "read_at"],
    )

    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_access_source", type_="check")
        batch.drop_constraint("ck_agent_runs_access_identity", type_="check")
        batch.create_check_constraint(
            "ck_agent_runs_access_source",
            "access_source IN ('console', 'public', 'api', 'automation')",
        )
        batch.create_check_constraint(
            "ck_agent_runs_access_identity",
            "(access_source = 'console' "
            "AND requested_by_user_id IS NOT NULL "
            "AND consumer_id = requested_by_user_id "
            "AND execution_user_id = requested_by_user_id) OR "
            "(access_source = 'automation' "
            "AND requested_by_user_id IS NOT NULL "
            "AND consumer_id = requested_by_user_id "
            "AND execution_user_id IS NOT NULL) OR "
            "(access_source IN ('public', 'api') AND requested_by_user_id IS NULL)",
        )

    with op.batch_alter_table("tool_invocations") as batch:
        batch.drop_constraint("ck_tool_invocations_access_source", type_="check")
        batch.create_check_constraint(
            "ck_tool_invocations_access_source",
            "access_source IN ('console', 'public', 'api', 'automation')",
        )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM tool_invocations WHERE access_source = 'automation'"
        )
    ):
        raise RuntimeError("Remove automation tool invocations before downgrading.")
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM agent_runs WHERE access_source = 'automation'")
    ):
        raise RuntimeError("Remove automation runs before downgrading.")

    with op.batch_alter_table("tool_invocations") as batch:
        batch.drop_constraint("ck_tool_invocations_access_source", type_="check")
        batch.create_check_constraint(
            "ck_tool_invocations_access_source",
            "access_source IN ('console', 'public', 'api')",
        )

    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_access_source", type_="check")
        batch.drop_constraint("ck_agent_runs_access_identity", type_="check")
        batch.create_check_constraint(
            "ck_agent_runs_access_source",
            "access_source IN ('console', 'public', 'api')",
        )
        batch.create_check_constraint(
            "ck_agent_runs_access_identity",
            "(access_source = 'console' AND requested_by_user_id IS NOT NULL "
            "AND consumer_id = requested_by_user_id "
            "AND execution_user_id = requested_by_user_id) OR "
            "(access_source IN ('public', 'api') AND requested_by_user_id IS NULL)",
        )

    op.drop_index("ix_user_notifications_unread", table_name="user_notifications")
    op.drop_index("ix_user_notifications_user_inbox", table_name="user_notifications")
    op.drop_index("ix_user_notifications_workspace_id", table_name="user_notifications")
    op.drop_index("ix_user_notifications_user_id", table_name="user_notifications")
    op.drop_table("user_notifications")

    op.drop_index(
        "ix_automation_executions_unclosed_notifications",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_automation_executions_pending_dispatch",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_automation_executions_lookup",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_automation_executions_owner_user_id",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_automation_executions_automation_id",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_automation_executions_workspace_id",
        table_name="automation_executions",
    )
    op.drop_table("automation_executions")

    op.drop_index("ix_automations_workspace_owner", table_name="automations")
    op.drop_index("ix_automations_due", table_name="automations")
    op.drop_index("ix_automations_next_run_at", table_name="automations")
    op.drop_index("ix_automations_target_app_id", table_name="automations")
    op.drop_index("ix_automations_owner_user_id", table_name="automations")
    op.drop_index("ix_automations_workspace_id", table_name="automations")
    op.drop_table("automations")
