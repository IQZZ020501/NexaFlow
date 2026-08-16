"""Make legacy evaluation answer points optional."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608160002"
down_revision: str | None = "202608160001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_evaluation_cases") as batch_op:
        batch_op.alter_column(
            "answer_points",
            existing_type=sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_evaluation_cases") as batch_op:
        batch_op.alter_column(
            "answer_points",
            existing_type=sa.JSON(),
            nullable=False,
            server_default=None,
        )
