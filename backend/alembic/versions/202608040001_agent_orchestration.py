"""agent orchestration state

Revision ID: 202608040001
Revises: 202608030002
Create Date: 2026-08-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608040001"
down_revision: str | None = "202608030002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.add_column(
            sa.Column("plan_revision", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("pending_approval", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("budget", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
        batch.add_column(
            sa.Column("usage", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
        batch.add_column(sa.Column("stop_reason", sa.String(length=80), nullable=True))
        batch.add_column(
            sa.Column("resumable", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('planning', 'planned', 'running', 'awaiting_approval', 'succeeded', 'failed')",
        )

    if op.get_bind().dialect.name != "sqlite":
        for name in ("plan_revision", "budget", "usage", "resumable"):
            op.alter_column("agent_runs", name, server_default=None)


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE agent_runs SET status = 'failed' "
            "WHERE status = 'awaiting_approval'"
        )
    )
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("ck_agent_runs_status", type_="check")
        batch.create_check_constraint(
            "ck_agent_runs_status",
            "status IN ('planning', 'planned', 'running', 'succeeded', 'failed')",
        )
        batch.drop_column("resumable")
        batch.drop_column("stop_reason")
        batch.drop_column("usage")
        batch.drop_column("budget")
        batch.drop_column("pending_approval")
        batch.drop_column("plan_revision")
