"""agent published flag

Revision ID: 202608040004
Revises: 202608040002
Create Date: 2026-08-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608040004"
down_revision: str | None = "202608040002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("agents", "published", server_default=None)


def downgrade() -> None:
    op.drop_column("agents", "published")
