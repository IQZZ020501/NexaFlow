"""Add application interaction configuration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608120004"
down_revision: str | None = "202608120003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "interaction_config",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "attachment_context",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.create_table(
        "workflow_uploads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category IN ('document', 'image', 'audio')",
            name="ck_workflow_uploads_category",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_workflow_uploads_size"),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"]
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_workflow_uploads_agent_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(
        op.f("ix_workflow_uploads_expires_at"),
        "workflow_uploads",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_uploads_agent_id"),
        "workflow_uploads",
        ["agent_id"],
        unique=False,
    )
    op.create_table(
        "workflow_upload_storage_cleanups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_workflow_upload_cleanups_size",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(
        op.f("ix_workflow_upload_storage_cleanups_next_attempt_at"),
        "workflow_upload_storage_cleanups",
        ["next_attempt_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_upload_storage_cleanups_uploaded_by_user_id"),
        "workflow_upload_storage_cleanups",
        ["uploaded_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_upload_storage_cleanups_workspace_id"),
        "workflow_upload_storage_cleanups",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_uploads_uploaded_by_user_id"),
        "workflow_uploads",
        ["uploaded_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_uploads_workspace_id"),
        "workflow_uploads",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workflow_upload_storage_cleanups_workspace_id"),
        table_name="workflow_upload_storage_cleanups",
    )
    op.drop_index(
        op.f("ix_workflow_upload_storage_cleanups_uploaded_by_user_id"),
        table_name="workflow_upload_storage_cleanups",
    )
    op.drop_index(
        op.f("ix_workflow_upload_storage_cleanups_next_attempt_at"),
        table_name="workflow_upload_storage_cleanups",
    )
    op.drop_table("workflow_upload_storage_cleanups")
    op.drop_index(op.f("ix_workflow_uploads_workspace_id"), table_name="workflow_uploads")
    op.drop_index(
        op.f("ix_workflow_uploads_uploaded_by_user_id"),
        table_name="workflow_uploads",
    )
    op.drop_index(op.f("ix_workflow_uploads_agent_id"), table_name="workflow_uploads")
    op.drop_index(op.f("ix_workflow_uploads_expires_at"), table_name="workflow_uploads")
    op.drop_table("workflow_uploads")
    op.drop_column("agent_runs", "attachment_context")
    op.drop_column("agents", "interaction_config")
