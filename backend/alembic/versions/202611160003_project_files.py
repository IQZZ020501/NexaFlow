"""Persist owner-scoped project files and immutable path revisions."""

import sqlalchemy as sa

from alembic import op

revision = "202611160003"
down_revision = "202611160002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_projects_owner",
        "agent_projects",
        ["workspace_id", "created_by_user_id"],
    )
    op.create_table(
        "project_file_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("agent_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", sa.String(36), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("invocation_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "path", "revision", name="uq_project_file_revision"
        ),
        sa.CheckConstraint("role IN ('source', 'work')", name="ck_project_file_role"),
        sa.CheckConstraint(
            "size_bytes BETWEEN 0 AND 5242880", name="ck_project_file_size"
        ),
        sa.CheckConstraint(
            "(deleted AND size_bytes = 0) OR (NOT deleted AND size_bytes > 0)",
            name="ck_project_file_deleted_size",
        ),
    )
    op.create_index(
        "ix_project_file_versions_path",
        "project_file_versions",
        ["project_id", "path", "revision"],
    )
    op.create_table(
        "project_run_states",
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("agent_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_heads", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("dependency_locks", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("project_run_states")
    op.drop_table("project_file_versions")
    op.drop_table("agent_projects")
