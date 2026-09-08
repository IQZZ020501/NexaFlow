"""Add global and workspace announcements with per-user read state."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202609070001"
down_revision: str | None = "202609060004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('global', 'workspace')",
            name="ck_announcements_scope_type",
        ),
        sa.CheckConstraint(
            "(scope_type = 'global' AND workspace_id IS NULL) OR "
            "(scope_type = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_announcements_scope_workspace",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_announcements_severity",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_announcements_status",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR published_at IS NULL OR expires_at > published_at",
            name="ck_announcements_expiry_after_publish",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_announcements_scope_type"),
        "announcements",
        ["scope_type"],
    )
    op.create_index(
        op.f("ix_announcements_workspace_id"),
        "announcements",
        ["workspace_id"],
    )
    op.create_index(
        op.f("ix_announcements_published_at"),
        "announcements",
        ["published_at"],
    )
    op.create_index(
        op.f("ix_announcements_expires_at"),
        "announcements",
        ["expires_at"],
    )
    op.create_index(
        op.f("ix_announcements_created_by_user_id"),
        "announcements",
        ["created_by_user_id"],
    )
    op.create_index(
        op.f("ix_announcements_updated_by_user_id"),
        "announcements",
        ["updated_by_user_id"],
    )
    op.create_index(
        "ix_announcements_visible",
        "announcements",
        ["scope_type", "workspace_id", "status", "published_at", "expires_at"],
    )
    op.create_table(
        "announcement_reads",
        sa.Column("announcement_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["announcement_id"],
            ["announcements.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "announcement_id",
            "user_id",
            name="pk_announcement_reads",
        ),
    )
    op.create_index(
        "ix_announcement_reads_user",
        "announcement_reads",
        ["user_id", "read_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_announcement_reads_user", table_name="announcement_reads")
    op.drop_table("announcement_reads")
    op.drop_index("ix_announcements_visible", table_name="announcements")
    op.drop_index(
        op.f("ix_announcements_updated_by_user_id"),
        table_name="announcements",
    )
    op.drop_index(
        op.f("ix_announcements_created_by_user_id"),
        table_name="announcements",
    )
    op.drop_index(op.f("ix_announcements_expires_at"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_published_at"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_workspace_id"), table_name="announcements")
    op.drop_index(op.f("ix_announcements_scope_type"), table_name="announcements")
    op.drop_table("announcements")
