"""Add resource folders to registered models."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202609060002"
down_revision: str | None = "202609060001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_resource_folders_resource_type",
        "resource_folders",
        type_="check",
    )
    op.create_check_constraint(
        "ck_resource_folders_resource_type",
        "resource_folders",
        "resource_type IN ('knowledge', 'application', 'model', 'tool')",
    )
    op.add_column("model", sa.Column("folder_id", sa.String(length=36), nullable=True))
    op.create_index(op.f("ix_model_folder_id"), "model", ["folder_id"])
    op.create_foreign_key(
        "fk_model_folder_workspace",
        "model",
        "resource_folders",
        ["workspace_id", "folder_id"],
        ["workspace_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_model_folder_workspace", "model", type_="foreignkey")
    op.drop_index(op.f("ix_model_folder_id"), table_name="model")
    op.drop_column("model", "folder_id")
    op.execute(sa.text("DELETE FROM resource_folders WHERE resource_type = 'model'"))
    op.drop_constraint(
        "ck_resource_folders_resource_type",
        "resource_folders",
        type_="check",
    )
    op.create_check_constraint(
        "ck_resource_folders_resource_type",
        "resource_folders",
        "resource_type IN ('knowledge', 'application', 'tool')",
    )
