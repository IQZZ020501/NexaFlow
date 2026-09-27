"""Add the per-Agent image generation model selection."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609270001"
down_revision: str | None = "202609250001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: agents without a selection keep using the single active image
    # model of their workspace, which is the pre-existing behaviour.
    op.add_column(
        "agents",
        sa.Column("image_model_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_agents_image_model_id",
        "agents",
        "model",
        ["image_model_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_agents_image_model_id"),
        "agents",
        ["image_model_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agents_image_model_id"), table_name="agents")
    op.drop_constraint("fk_agents_image_model_id", "agents", type_="foreignkey")
    op.drop_column("agents", "image_model_id")
