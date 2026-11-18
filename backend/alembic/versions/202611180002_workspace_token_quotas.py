"""Durable workspace monthly model usage and in-flight reservations."""

import sqlalchemy as sa

from alembic import op

revision = "202611180002"
down_revision = "202611180001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_token_months",
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("period", sa.String(7), primary_key=True),
        sa.Column("used_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "used_tokens >= 0 AND reserved_tokens >= 0",
            name="ck_workspace_token_months_nonnegative",
        ),
    )
    op.create_table(
        "model_usage_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=False),
        sa.Column("charged_tokens", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reserved_tokens > 0 AND charged_tokens >= 0",
            name="ck_model_usage_reservation_tokens",
        ),
        sa.CheckConstraint(
            "state IN ('dispatched', 'settled', 'uncertain')",
            name="ck_model_usage_reservation_state",
        ),
    )
    op.create_index(
        "ix_model_usage_reservations_workspace_id",
        "model_usage_reservations",
        ["workspace_id"],
    )


def downgrade():
    bind = op.get_bind()
    for name in ("model_usage_reservations", "workspace_token_months"):
        table = sa.Table(name, sa.MetaData(), autoload_with=bind)
        if bind.scalar(sa.select(sa.func.count()).select_from(table)):
            raise RuntimeError(
                "Cannot downgrade a nonempty token ledger. Stop model requests and preserve the accounting tables when rolling back code."
            )
    op.drop_table("model_usage_reservations")
    op.drop_table("workspace_token_months")
