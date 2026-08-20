"""Persist run regeneration lineage and per-consumer feedback."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608190002"
down_revision: str | None = "202608190001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add regeneration lineage and feedback fields to the ``agent_runs`` table."""
    op.add_column(
        "agent_runs",
        sa.Column("regenerated_from_run_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("feedback", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("feedback_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table("agent_runs") as batch:
        batch.create_foreign_key(
            "fk_agent_runs_regenerated_from",
            "agent_runs",
            ["workspace_id", "regenerated_from_run_id"],
            ["workspace_id", "id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_agent_runs_feedback",
            "feedback IS NULL OR feedback IN ('positive', 'negative')",
        )
    op.create_index(
        "ix_agent_runs_regenerated_from_run_id",
        "agent_runs",
        ["regenerated_from_run_id"],
    )


def downgrade() -> None:
    """
    Remove regeneration lineage and feedback fields from the agent_runs table.
    """
    op.drop_index("ix_agent_runs_regenerated_from_run_id", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_feedback", type_="check")
        batch.drop_constraint(
            "fk_agent_runs_regenerated_from", type_="foreignkey"
        )
        batch.drop_column("feedback_updated_at")
        batch.drop_column("feedback")
        batch.drop_column("regenerated_from_run_id")
