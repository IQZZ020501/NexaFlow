"""Retain bounded MCP result bodies in the existing invocation ledger."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610250002"
down_revision: str | None = "202610250001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_invocations", sa.Column("full_result", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    table = sa.table("tool_invocations", sa.column("full_result"))
    if op.get_bind().scalar(
        sa.select(sa.func.count())
        .select_from(table)
        .where(table.c.full_result.is_not(None))
    ):
        raise RuntimeError("Cannot remove retained Tool result bodies.")
    op.drop_column("tool_invocations", "full_result")
