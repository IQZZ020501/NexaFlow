"""Add workspace governance settings."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608200001"
down_revision: str | None = "202608190002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the workspace governance settings table."""
    op.create_table(
        "workspace_governance",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("daily_run_limit", sa.Integer(), nullable=True),
        sa.Column("monthly_token_limit", sa.BigInteger(), nullable=True),
        sa.Column("alert_threshold_percent", sa.Integer(), server_default="80", nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )


def downgrade() -> None:
    """Remove the workspace governance table from the database schema."""
    op.drop_table("workspace_governance")
