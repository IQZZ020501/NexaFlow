"""Add composite partial indexes for workspace analytics time-range queries."""

import sqlalchemy as sa

from alembic import op

revision = "202611260001"
down_revision = "202611240001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_agent_runs_workspace_created_root",
        "agent_runs",
        ["workspace_id", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("depth = 0"),
        sqlite_where=sa.text("depth = 0"),
    )
    op.create_index(
        "ix_tool_invocations_workspace_created_tool",
        "tool_invocations",
        ["workspace_id", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("tool_id IS NOT NULL"),
        sqlite_where=sa.text("tool_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index(
        "ix_tool_invocations_workspace_created_tool",
        table_name="tool_invocations",
    )
    op.drop_index(
        "ix_agent_runs_workspace_created_root",
        table_name="agent_runs",
    )
