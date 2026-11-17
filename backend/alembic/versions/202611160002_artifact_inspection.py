"""Associate bounded file inspection with immutable bytes and their invocation."""

import sqlalchemy as sa

from alembic import op

revision = "202611160002"
down_revision = "202611160001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generated_artifacts", sa.Column("invocation_id", sa.String(36), nullable=True))
    op.add_column("generated_artifacts", sa.Column("inspection", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("generated_artifacts", "inspection")
    op.drop_column("generated_artifacts", "invocation_id")
