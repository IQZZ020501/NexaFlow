"""Persist Run-private sandbox ownership and command fencing."""

import sqlalchemy as sa

from alembic import op

revision = "202610140001"
down_revision = "202610120001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "execution_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("owner_key", sa.String(64), nullable=False),
        sa.Column("sandbox_id", sa.String(128)),
        sa.Column("image", sa.String(512), nullable=False),
        sa.Column("profile_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("staged_packages", sa.JSON(), nullable=False),
        sa.Column("environments", sa.JSON(), nullable=False),
        sa.Column("capacity_token", sa.String(64)),
        sa.Column("consumer_key", sa.String(128)),
        sa.Column("holder", sa.String(64)),
        sa.Column("holder_expires_at", sa.DateTime(timezone=True)),
        *(
            sa.Column(name, sa.DateTime(timezone=True), nullable=False)
            for name in ("expires_at", "last_used_at", "created_at", "updated_at")
        ),
        sa.CheckConstraint(
            "purpose IN ('run', 'mcp')", name="ck_execution_sessions_purpose"
        ),
        sa.CheckConstraint(
            "state IN ('creating', 'ready', 'closing', 'closed')",
            name="ck_execution_sessions_state",
        ),
    )
    for name in ("workspace_id", "run_id", "sandbox_id", "state", "expires_at"):
        op.create_index(f"ix_execution_sessions_{name}", "execution_sessions", [name])
    op.create_index(
        "uq_execution_sessions_live_owner",
        "execution_sessions",
        ["workspace_id", "run_id", "purpose", "owner_key"],
        unique=True,
        postgresql_where=sa.text("state != 'closed'"),
        sqlite_where=sa.text("state != 'closed'"),
    )


def downgrade():
    op.drop_table("execution_sessions")
