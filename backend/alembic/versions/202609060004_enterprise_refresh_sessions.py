"""Link refresh sessions to enterprise identities."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202609060004"
down_revision: str | None = "202609060003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_sessions",
        sa.Column("enterprise_identity_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        op.f("ix_refresh_sessions_enterprise_identity_id"),
        "refresh_sessions",
        ["enterprise_identity_id"],
    )
    op.create_foreign_key(
        "fk_refresh_sessions_enterprise_identity_id",
        "refresh_sessions",
        "enterprise_identities",
        ["enterprise_identity_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_refresh_sessions_enterprise_identity_id",
        "refresh_sessions",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_refresh_sessions_enterprise_identity_id"),
        table_name="refresh_sessions",
    )
    op.drop_column("refresh_sessions", "enterprise_identity_id")
