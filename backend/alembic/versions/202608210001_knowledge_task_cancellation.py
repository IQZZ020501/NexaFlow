"""Allow knowledge tasks to be stopped explicitly."""

from collections.abc import Sequence

from alembic import op


revision: str = "202608210001"
down_revision: str | None = "202608200007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_tasks") as batch:
        batch.drop_constraint("ck_knowledge_tasks_status", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_tasks_status",
            "status IN ('queued', 'running', 'succeeded', 'failed', "
            "'cancelling', 'cancelled')",
        )


def downgrade() -> None:
    op.execute(
        "UPDATE knowledge_tasks SET status = 'failed' "
        "WHERE status IN ('cancelling', 'cancelled')"
    )
    with op.batch_alter_table("knowledge_tasks") as batch:
        batch.drop_constraint("ck_knowledge_tasks_status", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_tasks_status",
            "status IN ('queued', 'running', 'succeeded', 'failed')",
        )
