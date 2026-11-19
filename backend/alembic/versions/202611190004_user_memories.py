"""User-owned long-term memories and recoverable extraction jobs."""

import sqlalchemy as sa

from alembic import op

revision = "202611190004"
down_revision = "202611190003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_memory_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("automatic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_user_memory_owner"),
    )
    for field in ("workspace_id", "user_id"):
        op.create_index(
            f"ix_user_memory_preferences_{field}", "user_memory_preferences", [field]
        )
    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("user_memory_preferences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("content", sa.String(600), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("source_run_id", sa.String(36), nullable=True),
        sa.Column("source_quote", sa.String(600), nullable=False, server_default=""),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "profile_id", "project_id", "key", name="uq_user_memory_key"
        ),
        sa.CheckConstraint(
            "category IN ('preference', 'background', 'goal', 'project')",
            name="ck_user_memory_category",
        ),
        sa.CheckConstraint(
            "origin IN ('manual', 'explicit', 'automatic')",
            name="ck_user_memory_origin",
        ),
    )
    op.create_index("ix_user_memories_profile_id", "user_memories", ["profile_id"])
    op.create_table(
        "user_memory_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("user_memory_preferences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done')", name="ck_user_memory_job_status"
        ),
    )
    op.create_index(
        "ix_user_memory_jobs_profile_id", "user_memory_jobs", ["profile_id"]
    )
    op.create_index(
        "ix_user_memory_jobs_available_at", "user_memory_jobs", ["available_at"]
    )


def downgrade():
    op.drop_table("user_memory_jobs")
    op.drop_table("user_memories")
    op.drop_table("user_memory_preferences")
