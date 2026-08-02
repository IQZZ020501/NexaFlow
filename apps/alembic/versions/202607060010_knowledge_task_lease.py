"""knowledge task lease

Revision ID: 202607060010
Revises: 202607060009
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202607060010"
down_revision: str | None = "202607060009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_tasks",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_tasks",
        sa.Column("worker_task_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_tasks", "worker_task_id")
    op.drop_column("knowledge_tasks", "lease_expires_at")
