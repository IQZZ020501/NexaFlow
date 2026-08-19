"""Add one-time workspace invitations."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608200003"
down_revision: str | None = "202608200002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_workspace_invitations_role"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"])
    op.create_index(
        "ix_workspace_invitations_token_hash",
        "workspace_invitations",
        ["token_hash"],
        unique=True,
    )
    op.create_index("ix_workspace_invitations_invited_by_user_id", "workspace_invitations", ["invited_by_user_id"])
    op.create_index("ix_workspace_invitations_expires_at", "workspace_invitations", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_workspace_invitations_expires_at", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_invited_by_user_id", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_token_hash", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_workspace_id", table_name="workspace_invitations")
    op.drop_table("workspace_invitations")
