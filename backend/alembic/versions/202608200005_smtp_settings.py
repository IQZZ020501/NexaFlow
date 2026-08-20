"""Add global SMTP settings."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608200005"
down_revision: str | None = "202608200004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the singleton SMTP settings table."""
    op.create_table(
        "smtp_settings",
        sa.Column(
            "id",
            sa.String(length=36),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
        sa.Column("host", sa.String(length=255), server_default="", nullable=False),
        sa.Column("port", sa.Integer(), server_default="587", nullable=False),
        sa.Column(
            "username", sa.String(length=255), server_default="", nullable=False
        ),
        sa.Column("password_ciphertext", sa.Text(), nullable=True),
        sa.Column("password_hint", sa.String(length=32), nullable=True),
        sa.Column(
            "security",
            sa.String(length=20),
            server_default="starttls",
            nullable=False,
        ),
        sa.Column(
            "from_email", sa.String(length=255), server_default="", nullable=False
        ),
        sa.Column(
            "from_name", sa.String(length=120), server_default="", nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), server_default="10", nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 'default'", name="ck_smtp_settings_singleton"),
        sa.CheckConstraint("port BETWEEN 1 AND 65535", name="ck_smtp_settings_port"),
        sa.CheckConstraint(
            "security IN ('none', 'starttls', 'ssl')",
            name="ck_smtp_settings_security",
        ),
        sa.CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 120",
            name="ck_smtp_settings_timeout",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Remove the global SMTP settings table."""
    op.drop_table("smtp_settings")
