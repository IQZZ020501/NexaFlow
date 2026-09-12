"""Remove configurable Agent knowledge retrieval modes."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202609110003"
down_revision: str | None = "202609110002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_agent_run_snapshots_knowledge_query_mode",
        "agent_run_snapshots",
        type_="check",
    )
    op.drop_column("agent_run_snapshots", "knowledge_query_mode")
    op.drop_constraint(
        "ck_agents_knowledge_query_mode",
        "agents",
        type_="check",
    )
    op.drop_column("agents", "knowledge_query_mode")


def downgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "knowledge_query_mode",
            sa.String(length=20),
            nullable=False,
            server_default="required",
        ),
    )
    op.create_check_constraint(
        "ck_agents_knowledge_query_mode",
        "agents",
        "knowledge_query_mode IN ('required', 'agentic')",
    )
    op.add_column(
        "agent_run_snapshots",
        sa.Column(
            "knowledge_query_mode",
            sa.String(length=20),
            nullable=False,
            server_default="agentic",
        ),
    )
    op.alter_column(
        "agent_run_snapshots",
        "knowledge_query_mode",
        server_default=None,
    )
    op.create_check_constraint(
        "ck_agent_run_snapshots_knowledge_query_mode",
        "agent_run_snapshots",
        "knowledge_query_mode IN ('required', 'agentic')",
    )
