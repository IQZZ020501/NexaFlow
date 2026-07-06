"""knowledge bases resource permissions

Revision ID: 202607050004
Revises: 202607050003
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202607050004"
down_revision: str | None = "202607050003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_knowledge_bases_status"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_knowledge_base_workspace_id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_knowledge_base_workspace_name"),
    )
    op.create_index(op.f("ix_knowledge_bases_created_by_user_id"), "knowledge_bases", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_knowledge_bases_workspace_id"), "knowledge_bases", ["workspace_id"], unique=False)

    op.create_table(
        "resource_permissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("permission", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("permission IN ('view', 'edit')", name="ck_resource_permissions_permission"),
        sa.CheckConstraint("resource_type IN ('knowledge_base')", name="ck_resource_permissions_resource_type"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspace_memberships.workspace_id", "workspace_memberships.user_id"],
            name="fk_resource_permission_workspace_user",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "resource_type",
            "resource_id",
            "user_id",
            name="uq_resource_permission_user",
        ),
    )
    op.create_index(op.f("ix_resource_permissions_resource_id"), "resource_permissions", ["resource_id"], unique=False)
    op.create_index(op.f("ix_resource_permissions_resource_type"), "resource_permissions", ["resource_type"], unique=False)
    op.create_index(op.f("ix_resource_permissions_user_id"), "resource_permissions", ["user_id"], unique=False)
    op.create_index(op.f("ix_resource_permissions_workspace_id"), "resource_permissions", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_resource_permissions_workspace_id"), table_name="resource_permissions")
    op.drop_index(op.f("ix_resource_permissions_user_id"), table_name="resource_permissions")
    op.drop_index(op.f("ix_resource_permissions_resource_type"), table_name="resource_permissions")
    op.drop_index(op.f("ix_resource_permissions_resource_id"), table_name="resource_permissions")
    op.drop_table("resource_permissions")

    op.drop_index(op.f("ix_knowledge_bases_workspace_id"), table_name="knowledge_bases")
    op.drop_index(op.f("ix_knowledge_bases_created_by_user_id"), table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
