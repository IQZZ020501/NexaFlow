"""Persist Agent answer-grounding status and bounded verifier metadata."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608190001"
down_revision: str | None = "202608170003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "grounding_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "grounding_meta",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.alter_column(
        "agent_runs",
        "grounding_status",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "agent_runs",
        "grounding_meta",
        existing_type=sa.JSON(),
        existing_nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "grounding_meta")
    op.drop_column("agent_runs", "grounding_status")
