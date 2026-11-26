"""Add global audit log retention settings table."""

import sqlalchemy as sa

from alembic import op

revision = "202611260003"
down_revision = "202611260002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_retention_settings",
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
            server_default="default",
        ),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 'default'", name="ck_audit_retention_settings_singleton"),
        sa.CheckConstraint(
            "retention_days IS NULL OR (retention_days >= 1 AND retention_days <= 3650)",
            name="ck_audit_retention_settings_days",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("audit_retention_settings")
