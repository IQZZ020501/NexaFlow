"""Add app_type to agents (agent | workflow)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608120001"
down_revision: str | None = "202608110001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(
            sa.Column(
                "app_type",
                sa.String(length=20),
                nullable=False,
                server_default="agent",
            )
        )
        batch.create_check_constraint(
            "ck_agents_app_type",
            "app_type IN ('agent', 'workflow')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_constraint("ck_agents_app_type", type_="check")
        batch.drop_column("app_type")
