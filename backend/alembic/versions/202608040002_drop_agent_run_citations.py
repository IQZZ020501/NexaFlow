"""drop agent run citations

Revision ID: 202608040002
Revises: 202608040001
Create Date: 2026-08-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608040002"
down_revision: str | None = "202608040001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("agent_runs", "citations")


def downgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "citations",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.alter_column("agent_runs", "citations", server_default=None)
