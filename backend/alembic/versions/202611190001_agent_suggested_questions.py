"""Persist related questions with the Agent answer that generated them."""

import sqlalchemy as sa

from alembic import op

revision = "202611190001"
down_revision = "202611180002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agent_run_states",
        sa.Column("suggested_questions", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade():
    op.drop_column("agent_run_states", "suggested_questions")
