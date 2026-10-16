"""Record when recovery last re-published a claimable Agent Run."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610120001"
down_revision: str | None = "202609270003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run_states",
        sa.Column("redispatched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_run_states", "redispatched_at")
