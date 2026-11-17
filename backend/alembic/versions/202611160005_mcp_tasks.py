"""Persist remote task identity and cancellation intent independently of workers."""

import sqlalchemy as sa

from alembic import op

revision = "202611160005"
down_revision = "202611160004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mcp_servers",
        sa.Column(
            "long_task_contracts", sa.JSON(), nullable=False, server_default="{}"
        ),
    )
    op.create_table(
        "mcp_remote_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invocation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("server_binding", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(255), nullable=False),
        sa.Column("contract", sa.JSON(), nullable=False),
        sa.Column("remote_id", sa.String(512)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("cancel_owner", sa.String(36)),
        sa.Column("cancel_lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_cancel_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_attempts", sa.Integer(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(1000)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_mcp_remote_tasks_cleanup", "mcp_remote_tasks", ["next_cancel_at", "status"]
    )


def downgrade():
    op.drop_table("mcp_remote_tasks")
    op.drop_column("mcp_servers", "long_task_contracts")
