"""Add durable workflow form input status."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608140001"
down_revision: str | None = "202608120004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_STATUSES = (
    "queued",
    "planning",
    "planned",
    "running",
    "awaiting_approval",
    "awaiting_input",
)
LEGACY_ACTIVE_STATUSES = ACTIVE_STATUSES[:-1]


def _active_index(statuses: tuple[str, ...]) -> None:
    op.create_index(
        "uq_agent_runs_active_conversation",
        "agent_runs",
        [
            "workspace_id",
            "agent_id",
            "access_source",
            "consumer_id",
            "conversation_id",
        ],
        unique=True,
        postgresql_where=sa.column("status").in_(statuses),
        sqlite_where=sa.column("status").in_(statuses),
    )


def upgrade() -> None:
    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('queued', 'planning', 'planned', 'running', "
            "'awaiting_approval', 'awaiting_input', 'succeeded', 'failed', 'cancelled')",
        )
    _active_index(ACTIVE_STATUSES)

    with op.batch_alter_table("workflow_node_executions") as batch:
        batch.drop_constraint("ck_workflow_node_executions_status", type_="check")
        batch.create_check_constraint(
            "ck_workflow_node_executions_status",
            "status IN ('running', 'awaiting_input', 'succeeded', 'failed', 'skipped')",
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE workflow_node_executions SET status = 'failed', "
            "error = 'Workflow form input was cancelled by downgrade' "
            "WHERE status = 'awaiting_input'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE agent_runs SET status = 'cancelled', "
            "last_error = 'Workflow form input was cancelled by downgrade' "
            "WHERE status = 'awaiting_input'"
        )
    )
    with op.batch_alter_table("workflow_node_executions") as batch:
        batch.drop_constraint("ck_workflow_node_executions_status", type_="check")
        batch.create_check_constraint(
            "ck_workflow_node_executions_status",
            "status IN ('running', 'succeeded', 'failed', 'skipped')",
        )

    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('queued', 'planning', 'planned', 'running', "
            "'awaiting_approval', 'succeeded', 'failed', 'cancelled')",
        )
    _active_index(LEGACY_ACTIVE_STATUSES)
