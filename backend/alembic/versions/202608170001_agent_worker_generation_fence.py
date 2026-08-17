"""Fence immutable Agent Runs from legacy workers.

Revision ID: 202608170001
Revises: 202608160005
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608170001"
down_revision: str | None = "202608160005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_STATUSES = (
    "queued",
    "planning",
    "planned",
    "running",
    "awaiting_approval",
    "awaiting_input",
)
_UNIFIED_STATUSES = (
    "queued_v2",
    "running_v2",
    "awaiting_approval_v2",
    "awaiting_input_v2",
)
_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


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


def _assert_unified_runs_drained(bind: sa.Connection) -> None:
    runs = sa.table(
        "agent_runs",
        sa.column("id", sa.String(36)),
        sa.column("configuration_source", sa.String(20)),
        sa.column("status", sa.String(20)),
    )
    active_run_id = bind.execute(
        sa.select(runs.c.id)
        .where(
            runs.c.configuration_source.in_(("draft", "published")),
            runs.c.status.not_in(_TERMINAL_STATUSES),
        )
        .limit(1)
    ).scalar_one_or_none()
    if active_run_id is not None:
        raise RuntimeError(
            "Unified Agent Runs must be drained before changing worker generation."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE agent_runs, agent_tool_calls, tool_invocations "
                "IN ACCESS EXCLUSIVE MODE"
            )
        )
    _assert_unified_runs_drained(bind)
    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('queued', 'planning', 'planned', 'running', "
            "'awaiting_approval', 'awaiting_input', 'queued_v2', 'running_v2', "
            "'awaiting_approval_v2', 'awaiting_input_v2', 'succeeded', "
            "'failed', 'cancelled')",
        )
        batch.create_check_constraint(
            "ck_agent_runs_worker_generation",
            "(configuration_source IN ('draft', 'published') AND status IN "
            "('queued_v2', 'running_v2', 'awaiting_approval_v2', "
            "'awaiting_input_v2', 'succeeded', 'failed', 'cancelled')) OR "
            "(configuration_source = 'legacy' AND status IN "
            "('queued', 'planning', 'planned', 'running', 'awaiting_approval', "
            "'awaiting_input', 'succeeded', 'failed', 'cancelled'))",
        )
    _active_index(_LEGACY_STATUSES + _UNIFIED_STATUSES)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE agent_runs, agent_tool_calls, tool_invocations "
                "IN ACCESS EXCLUSIVE MODE"
            )
        )
    _assert_unified_runs_drained(bind)
    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_worker_generation", type_="check")
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('queued', 'planning', 'planned', 'running', "
            "'awaiting_approval', 'awaiting_input', 'succeeded', 'failed', 'cancelled')",
        )
    _active_index(_LEGACY_STATUSES)
