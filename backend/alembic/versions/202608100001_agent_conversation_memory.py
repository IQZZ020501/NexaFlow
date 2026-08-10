"""Add conversation boundaries, durable summaries, and model usage."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608100001"
down_revision: str | None = "202608080002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACTIVE_STATUSES = "'queued', 'planning', 'planned', 'running', 'awaiting_approval'"


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("conversation_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column(
                "context_summary",
                sa.Text(),
                nullable=True,
                server_default="",
            )
        )
        batch.add_column(
            sa.Column(
                "model_usage",
                sa.JSON(),
                nullable=True,
                server_default="{}",
            )
        )

    # Existing runs retain the old single-thread behavior. Active work gets its
    # own id so a migration cannot create two rows in the new active index.
    op.execute(
        f"""
        WITH grouped AS (
            SELECT workspace_id, agent_id, requested_by_user_id, MIN(id) AS conversation_id
            FROM agent_runs
            GROUP BY workspace_id, agent_id, requested_by_user_id
        )
        UPDATE agent_runs AS runs
        SET conversation_id = CASE
            WHEN runs.status IN ({ACTIVE_STATUSES}) THEN runs.id
            ELSE grouped.conversation_id
        END,
            context_summary = COALESCE(runs.context_summary, ''),
            model_usage = COALESCE(runs.model_usage, '{{}}')
        FROM grouped
        WHERE runs.workspace_id = grouped.workspace_id
          AND runs.agent_id = grouped.agent_id
          AND runs.requested_by_user_id = grouped.requested_by_user_id
        """
    )

    with op.batch_alter_table("agent_runs") as batch:
        batch.alter_column("conversation_id", nullable=False)
        batch.alter_column("context_summary", nullable=False)
        batch.alter_column("model_usage", nullable=False)
        batch.create_index("ix_agent_runs_conversation_id", ["conversation_id"])

    op.create_index(
        "uq_agent_runs_active_conversation",
        "agent_runs",
        ["workspace_id", "agent_id", "requested_by_user_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({ACTIVE_STATUSES})"),
        sqlite_where=sa.text(f"status IN ({ACTIVE_STATUSES})"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_index("ix_agent_runs_conversation_id")
        batch.drop_column("model_usage")
        batch.drop_column("context_summary")
        batch.drop_column("conversation_id")
