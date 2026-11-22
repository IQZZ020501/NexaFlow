"""Separate personal models from the workspace catalog without changing existing access."""

import sqlalchemy as sa

from alembic import op

revision = "202611220001"
down_revision = "202611200002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("model") as batch:
        batch.add_column(
            sa.Column(
                "visibility", sa.String(20), nullable=False, server_default="workspace"
            )
        )
        batch.drop_constraint("uq_model_registry_model_workspace_name", type_="unique")
        batch.create_check_constraint(
            "ck_model_visibility", "visibility IN ('personal', 'workspace')"
        )
    op.create_index(
        "uq_model_workspace_name",
        "model",
        ["workspace_id", "name"],
        unique=True,
        postgresql_where=sa.text("visibility = 'workspace'"),
        sqlite_where=sa.text("visibility = 'workspace'"),
    )
    op.create_index(
        "uq_model_personal_owner_name",
        "model",
        ["workspace_id", "created_by_user_id", "name"],
        unique=True,
        postgresql_where=sa.text("visibility = 'personal'"),
        sqlite_where=sa.text("visibility = 'personal'"),
    )


def downgrade():
    # A downgrade cannot preserve both the old workspace-wide name uniqueness
    # and independent personal names without renaming/deleting user data.
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM model WHERE visibility = 'personal'")
    ):
        raise RuntimeError("Remove personal model configurations before downgrading.")
    op.drop_index("uq_model_personal_owner_name", table_name="model")
    op.drop_index("uq_model_workspace_name", table_name="model")
    with op.batch_alter_table("model") as batch:
        batch.drop_constraint("ck_model_visibility", type_="check")
        batch.drop_column("visibility")
        batch.create_unique_constraint(
            "uq_model_registry_model_workspace_name", ["workspace_id", "name"]
        )
