"""Add durable Workflow Agent child runs.

Revision ID: 202608170003
Revises: 202608170002
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608170003"
down_revision: str | None = "202608170002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
_ACTIVE_STATUSES = (
    "queued",
    "planning",
    "planned",
    "running",
    "awaiting_approval",
    "awaiting_input",
    "awaiting_child",
    "queued_v2",
    "running_v2",
    "awaiting_approval_v2",
    "awaiting_input_v2",
    "awaiting_child_v2",
)
_PREVIOUS_ACTIVE_STATUSES = tuple(
    status
    for status in _ACTIVE_STATUSES
    if status not in {"awaiting_child", "awaiting_child_v2"}
)


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


def _assert_runs_drained(bind: sa.Connection) -> None:
    runs = sa.table(
        "agent_runs",
        sa.column("id", sa.String(36)),
        sa.column("status", sa.String(20)),
    )
    active = bind.execute(
        sa.select(runs.c.id)
        .where(runs.c.status.not_in(_TERMINAL_STATUSES))
        .limit(1)
    ).scalar_one_or_none()
    if active is not None:
        raise RuntimeError(
            "Agent and Workflow Runs must be drained before enabling child runs."
        )


def _assert_no_children(bind: sa.Connection) -> None:
    runs = sa.table(
        "agent_runs",
        sa.column("id", sa.String(36)),
        sa.column("parent_run_id", sa.String(36)),
    )
    child = bind.execute(
        sa.select(runs.c.id).where(runs.c.parent_run_id.is_not(None)).limit(1)
    ).scalar_one_or_none()
    if child is not None:
        raise RuntimeError(
            "Workflow Agent child history exists; downgrade would lose lineage."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE agent_runs, workflow_node_executions "
                "IN ACCESS EXCLUSIVE MODE"
            )
        )
    _assert_runs_drained(bind)
    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    op.add_column(
        "agent_runs",
        sa.Column("root_run_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("parent_run_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("parent_node_id", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    runs = sa.table(
        "agent_runs",
        sa.column("id", sa.String(36)),
        sa.column("root_run_id", sa.String(36)),
    )
    bind.execute(runs.update().values(root_run_id=runs.c.id))
    with op.batch_alter_table("agent_runs") as batch:
        batch.alter_column("root_run_id", nullable=False)
        batch.alter_column("depth", server_default=None)
        batch.drop_constraint("ck_agent_runs_worker_generation", type_="check")
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.create_foreign_key(
            "fk_agent_runs_root_workspace",
            "agent_runs",
            ["workspace_id", "root_run_id"],
            ["workspace_id", "id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_agent_runs_parent_workspace",
            "agent_runs",
            ["workspace_id", "parent_run_id"],
            ["workspace_id", "id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_agent_runs_parent_node",
            ["parent_run_id", "parent_node_id"],
        )
        batch.create_check_constraint(
            "ck_agent_runs_parent_depth",
            "(depth = 0 AND parent_run_id IS NULL AND parent_node_id IS NULL "
            "AND root_run_id = id) OR "
            "(depth = 1 AND parent_run_id IS NOT NULL "
            "AND parent_node_id IS NOT NULL AND root_run_id = parent_run_id)",
        )
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('queued', 'planning', 'planned', 'running', "
            "'awaiting_approval', 'awaiting_input', 'awaiting_child', "
            "'queued_v2', 'running_v2', 'awaiting_approval_v2', "
            "'awaiting_input_v2', 'awaiting_child_v2', 'succeeded', "
            "'failed', 'cancelled')",
        )
        batch.create_check_constraint(
            "ck_agent_runs_worker_generation",
            "(configuration_source IN ('draft', 'published') AND status IN "
            "('queued_v2', 'running_v2', 'awaiting_approval_v2', "
            "'awaiting_input_v2', 'awaiting_child_v2', 'succeeded', 'failed', "
            "'cancelled')) OR (configuration_source = 'legacy' AND status IN "
            "('queued', 'planning', 'planned', 'running', 'awaiting_approval', "
            "'awaiting_input', 'awaiting_child', 'succeeded', 'failed', "
            "'cancelled'))",
        )
    op.create_index("ix_agent_runs_root_run_id", "agent_runs", ["root_run_id"])
    op.create_index("ix_agent_runs_parent_run_id", "agent_runs", ["parent_run_id"])
    _active_index(_ACTIVE_STATUSES)
    with op.batch_alter_table("workflow_node_executions") as batch:
        batch.drop_constraint("ck_workflow_node_executions_status", type_="check")
        batch.create_check_constraint(
            "ck_workflow_node_executions_status",
            "status IN ('running', 'awaiting_input', 'awaiting_child', "
            "'succeeded', 'failed', 'skipped')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE agent_runs, workflow_node_executions "
                "IN ACCESS EXCLUSIVE MODE"
            )
        )
    _assert_runs_drained(bind)
    _assert_no_children(bind)
    with op.batch_alter_table("workflow_node_executions") as batch:
        batch.drop_constraint("ck_workflow_node_executions_status", type_="check")
        batch.create_check_constraint(
            "ck_workflow_node_executions_status",
            "status IN ('running', 'awaiting_input', 'succeeded', 'failed', 'skipped')",
        )
    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    op.drop_index("ix_agent_runs_parent_run_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_root_run_id", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_worker_generation", type_="check")
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.drop_constraint("ck_agent_runs_parent_depth", type_="check")
        batch.drop_constraint("uq_agent_runs_parent_node", type_="unique")
        batch.drop_constraint("fk_agent_runs_parent_workspace", type_="foreignkey")
        batch.drop_constraint("fk_agent_runs_root_workspace", type_="foreignkey")
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
        batch.drop_column("depth")
        batch.drop_column("parent_node_id")
        batch.drop_column("parent_run_id")
        batch.drop_column("root_run_id")
    _active_index(_PREVIOUS_ACTIVE_STATUSES)
