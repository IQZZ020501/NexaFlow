"""Persist request identity, resource waiting and immutable artifact lineage."""

import sqlalchemy as sa

from alembic import op

revision = "202611160001"
down_revision = "202610250003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("request_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("request_hash", sa.String(64), nullable=True))
        batch.create_unique_constraint(
            "uq_agent_runs_request",
            ["workspace_id", "agent_id", "access_source", "consumer_id", "request_id"],
        )
    op.add_column(
        "tool_invocations",
        sa.Column("resource_wait", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "generated_artifacts", sa.Column("content_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "generated_artifacts",
        sa.Column("previous_artifact_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "execution_sessions",
        sa.Column(
            "capacity_reservation", sa.JSON(), nullable=False, server_default="{}"
        ),
    )
    op.add_column(
        "execution_sessions",
        sa.Column(
            "creation_pending", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade():
    op.drop_column("execution_sessions", "creation_pending")
    op.drop_column("execution_sessions", "capacity_reservation")
    op.drop_column("generated_artifacts", "previous_artifact_id")
    op.drop_column("generated_artifacts", "content_hash")
    op.drop_column("tool_invocations", "resource_wait")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_constraint("uq_agent_runs_request", type_="unique")
        batch.drop_column("request_hash")
        batch.drop_column("request_id")
