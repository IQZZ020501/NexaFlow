"""Persist host placement and transient creation reservations."""

import sqlalchemy as sa

from alembic import op

revision = "202611160006"
down_revision = "202611160005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "execution_sessions",
        sa.Column("host_id", sa.String(32), nullable=False, server_default="local"),
    )
    op.add_column(
        "execution_sessions",
        sa.Column("host_fingerprint", sa.String(64), nullable=False, server_default=""),
    )
    op.create_index("ix_execution_sessions_host_id", "execution_sessions", ["host_id"])
    op.create_table(
        "execution_placements",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36)),
        sa.Column("host_id", sa.String(32), nullable=False),
        sa.Column("host_fingerprint", sa.String(64), nullable=False),
        sa.Column("profile_fingerprint", sa.String(64), nullable=False),
        sa.Column("profiles", sa.JSON(), nullable=False),
        sa.Column("consumer_key", sa.String(128)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("run_id", "host_id", "expires_at"):
        op.create_index(
            f"ix_execution_placements_{name}", "execution_placements", [name]
        )


def downgrade():
    op.drop_table("execution_placements")
    op.drop_index("ix_execution_sessions_host_id", "execution_sessions")
    op.drop_column("execution_sessions", "host_fingerprint")
    op.drop_column("execution_sessions", "host_id")
