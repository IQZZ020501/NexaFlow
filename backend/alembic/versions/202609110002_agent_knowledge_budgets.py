"""Persist dedicated Agent knowledge retrieval budgets."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202609110002"
down_revision: str | None = "202609110001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run_snapshots",
        sa.Column(
            "max_knowledge_calls",
            sa.Integer(),
            nullable=False,
            server_default="6",
        ),
    )
    op.add_column(
        "agent_run_snapshots",
        sa.Column(
            "max_knowledge_rounds",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE agent_run_snapshots "
            "SET max_knowledge_calls = LEAST(6, max_tool_calls), "
            "max_knowledge_rounds = LEAST(3, max_turns)"
        )
    )
    op.create_check_constraint(
        "ck_agent_run_snapshots_max_knowledge_calls",
        "agent_run_snapshots",
        "max_knowledge_calls > 0 AND max_knowledge_calls <= max_tool_calls",
    )
    op.create_check_constraint(
        "ck_agent_run_snapshots_max_knowledge_rounds",
        "agent_run_snapshots",
        "max_knowledge_rounds > 0 AND max_knowledge_rounds <= max_turns",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_agent_run_snapshots_max_knowledge_rounds",
        "agent_run_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_run_snapshots_max_knowledge_calls",
        "agent_run_snapshots",
        type_="check",
    )
    op.drop_column("agent_run_snapshots", "max_knowledge_rounds")
    op.drop_column("agent_run_snapshots", "max_knowledge_calls")
