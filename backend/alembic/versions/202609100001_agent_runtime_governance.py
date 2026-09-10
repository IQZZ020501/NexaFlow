"""Persist Agent execution budgets and reproducibility snapshots."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202609100001"
down_revision: str | None = "202609090001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run_states",
        sa.Column("execution_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agent_run_states_execution_deadline_at",
        "agent_run_states",
        ["execution_deadline_at"],
    )

    op.add_column(
        "agent_run_snapshots",
        sa.Column(
            "max_runtime_seconds",
            sa.Float(),
            nullable=False,
            server_default="300",
        ),
    )
    op.add_column(
        "agent_run_snapshots",
        sa.Column("max_turns", sa.Integer(), nullable=False, server_default="8"),
    )
    op.add_column(
        "agent_run_snapshots",
        sa.Column("max_tool_calls", sa.Integer(), nullable=False, server_default="12"),
    )
    op.add_column(
        "agent_run_snapshots",
        sa.Column(
            "max_model_tokens",
            sa.Integer(),
            nullable=False,
            server_default="100000",
        ),
    )
    op.add_column(
        "agent_run_snapshots",
        sa.Column(
            "model_runtime_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "agent_run_snapshots",
        sa.Column(
            "knowledge_resource_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_run_snapshots
            SET model_runtime_snapshot = json_build_object(
                    'schema_version', 0,
                    'legacy', true,
                    'model_id', model_id,
                    'model_name', model_name
                ),
                knowledge_resource_snapshot = json_build_object(
                    'schema_version', 0,
                    'legacy', true,
                    'knowledge_base_ids', knowledge_base_ids
                )
            """
        )
    )
    op.create_check_constraint(
        "ck_agent_run_snapshots_runtime_seconds",
        "agent_run_snapshots",
        "max_runtime_seconds > 0 AND max_runtime_seconds <= 1800",
    )
    op.create_check_constraint(
        "ck_agent_run_snapshots_max_turns",
        "agent_run_snapshots",
        "max_turns > 0 AND max_turns <= 64",
    )
    op.create_check_constraint(
        "ck_agent_run_snapshots_max_tool_calls",
        "agent_run_snapshots",
        "max_tool_calls > 0 AND max_tool_calls <= 128",
    )
    op.create_check_constraint(
        "ck_agent_run_snapshots_max_model_tokens",
        "agent_run_snapshots",
        "max_model_tokens > 0 AND max_model_tokens <= 1000000",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_agent_run_snapshots_max_model_tokens",
        "agent_run_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_run_snapshots_max_tool_calls",
        "agent_run_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_run_snapshots_max_turns",
        "agent_run_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_run_snapshots_runtime_seconds",
        "agent_run_snapshots",
        type_="check",
    )
    op.drop_column("agent_run_snapshots", "knowledge_resource_snapshot")
    op.drop_column("agent_run_snapshots", "model_runtime_snapshot")
    op.drop_column("agent_run_snapshots", "max_model_tokens")
    op.drop_column("agent_run_snapshots", "max_tool_calls")
    op.drop_column("agent_run_snapshots", "max_turns")
    op.drop_column("agent_run_snapshots", "max_runtime_seconds")
    op.drop_index(
        "ix_agent_run_states_execution_deadline_at",
        table_name="agent_run_states",
    )
    op.drop_column("agent_run_states", "execution_deadline_at")
