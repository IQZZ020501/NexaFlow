"""Allow Agent resource permissions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608110001"
down_revision: str | None = "202608100003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("resource_permissions") as batch:
        batch.drop_constraint(
            "ck_resource_permissions_resource_type",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_resource_permissions_resource_type",
            "resource_type IN ('knowledge_base', 'agent')",
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM resource_permissions WHERE resource_type = 'agent'")
    )
    with op.batch_alter_table("resource_permissions") as batch:
        batch.drop_constraint(
            "ck_resource_permissions_resource_type",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_resource_permissions_resource_type",
            "resource_type IN ('knowledge_base')",
        )
