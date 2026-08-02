"""knowledge task progress columns

Revision ID: 202607060007
Revises: 202607060006
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202607060007"
down_revision: str | None = "202607060006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_column("knowledge_tasks", "total_items"):
        op.add_column(
            "knowledge_tasks",
            sa.Column("total_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    if not _has_column("knowledge_tasks", "processed_items"):
        op.add_column(
            "knowledge_tasks",
            sa.Column("processed_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    pass
