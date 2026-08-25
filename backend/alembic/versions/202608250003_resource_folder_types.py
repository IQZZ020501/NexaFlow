"""Separate resource folders by resource type."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608250003"
down_revision: str | None = "202608250002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resource_folders",
        sa.Column("resource_type", sa.String(length=20), nullable=True),
    )
    op.execute("UPDATE resource_folders SET resource_type = 'knowledge'")
    op.execute("UPDATE agents SET folder_id = NULL WHERE folder_id IS NOT NULL")
    op.execute("UPDATE tools SET folder_id = NULL WHERE folder_id IS NOT NULL")
    op.alter_column("resource_folders", "resource_type", nullable=False)
    op.create_index(
        op.f("ix_resource_folders_resource_type"),
        "resource_folders",
        ["resource_type"],
    )
    op.drop_constraint(
        "fk_resource_folders_parent_workspace",
        "resource_folders",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_resource_folders_workspace_parent_name",
        table_name="resource_folders",
    )
    op.create_unique_constraint(
        "uq_resource_folders_workspace_type_id",
        "resource_folders",
        ["workspace_id", "resource_type", "id"],
    )
    op.create_check_constraint(
        "ck_resource_folders_resource_type",
        "resource_folders",
        "resource_type IN ('knowledge', 'application', 'tool')",
    )
    op.create_foreign_key(
        "fk_resource_folders_parent_workspace_type",
        "resource_folders",
        "resource_folders",
        ["workspace_id", "resource_type", "parent_id"],
        ["workspace_id", "resource_type", "id"],
    )
    op.create_index(
        "uq_resource_folders_workspace_parent_name",
        "resource_folders",
        ["workspace_id", "resource_type", "parent_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_resource_folders_workspace_parent_name",
        table_name="resource_folders",
    )
    op.drop_constraint(
        "fk_resource_folders_parent_workspace_type",
        "resource_folders",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_resource_folders_resource_type",
        "resource_folders",
        type_="check",
    )
    op.drop_constraint(
        "uq_resource_folders_workspace_type_id",
        "resource_folders",
        type_="unique",
    )
    op.create_foreign_key(
        "fk_resource_folders_parent_workspace",
        "resource_folders",
        "resource_folders",
        ["workspace_id", "parent_id"],
        ["workspace_id", "id"],
    )
    op.create_index(
        "uq_resource_folders_workspace_parent_name",
        "resource_folders",
        ["workspace_id", "parent_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.drop_index(op.f("ix_resource_folders_resource_type"), table_name="resource_folders")
    op.drop_column("resource_folders", "resource_type")
