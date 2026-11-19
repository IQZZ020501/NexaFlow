"""Enable automatic memory by default while preserving saved preferences."""

import sqlalchemy as sa

from alembic import op

revision = "202611200001"
down_revision = "202611190004"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_memory_preferences") as batch:
        batch.alter_column(
            "automatic",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true(),
        )


def downgrade():
    with op.batch_alter_table("user_memory_preferences") as batch:
        batch.alter_column(
            "automatic",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.false(),
        )
