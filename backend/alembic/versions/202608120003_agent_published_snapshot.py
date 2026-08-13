"""Add the current published Agent configuration snapshot."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608120003"
down_revision: str | None = "202608120002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("published_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "published_snapshot")
