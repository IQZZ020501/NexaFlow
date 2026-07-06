"""workspace team descriptions

Revision ID: 202607060002
Revises: 202607060001
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202607060002"
down_revision: str | None = "202607060001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "teams",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("teams", "description")
    op.drop_column("workspaces", "description")
