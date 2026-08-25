"""Add shared resource folders for knowledge, applications, and tools."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608250002"
down_revision: str | None = "202608250001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_folders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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
            ["workspace_id", "parent_id"],
            ["resource_folders.workspace_id", "resource_folders.id"],
            name="fk_resource_folders_parent_workspace",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_resource_folders_workspace_id",
        ),
    )
    op.create_index(
        "uq_resource_folders_workspace_parent_name",
        "resource_folders",
        ["workspace_id", "parent_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        op.f("ix_resource_folders_workspace_id"),
        "resource_folders",
        ["workspace_id"],
    )
    op.create_index(
        op.f("ix_resource_folders_parent_id"),
        "resource_folders",
        ["parent_id"],
    )
    op.create_index(
        op.f("ix_resource_folders_created_by_user_id"),
        "resource_folders",
        ["created_by_user_id"],
    )

    for table_name, constraint_name in (
        ("knowledge", "fk_knowledge_folder_workspace"),
        ("agents", "fk_agents_folder_workspace"),
        ("tools", "fk_tools_folder_workspace"),
    ):
        op.add_column(table_name, sa.Column("folder_id", sa.String(length=36), nullable=True))
        op.create_index(op.f(f"ix_{table_name}_folder_id"), table_name, ["folder_id"])
        op.create_foreign_key(
            constraint_name,
            table_name,
            "resource_folders",
            ["workspace_id", "folder_id"],
            ["workspace_id", "id"],
        )


def downgrade() -> None:
    for table_name, constraint_name in (
        ("tools", "fk_tools_folder_workspace"),
        ("agents", "fk_agents_folder_workspace"),
        ("knowledge", "fk_knowledge_folder_workspace"),
    ):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        op.drop_index(op.f(f"ix_{table_name}_folder_id"), table_name=table_name)
        op.drop_column(table_name, "folder_id")

    op.drop_index(
        op.f("ix_resource_folders_created_by_user_id"),
        table_name="resource_folders",
    )
    op.drop_index(op.f("ix_resource_folders_parent_id"), table_name="resource_folders")
    op.drop_index(op.f("ix_resource_folders_workspace_id"), table_name="resource_folders")
    op.drop_index(
        "uq_resource_folders_workspace_parent_name",
        table_name="resource_folders",
    )
    op.drop_table("resource_folders")
