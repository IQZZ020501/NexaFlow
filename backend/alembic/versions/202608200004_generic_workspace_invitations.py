"""Allow reusable generic workspace invitations."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608200004"
down_revision: str | None = "202608200003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECIPIENT_CHECK = "ck_workspace_invitations_recipient"


def upgrade() -> None:
    """Allow all recipient fields to be null together for generic invitations."""
    with op.batch_alter_table("workspace_invitations") as batch:
        batch.alter_column(
            "username", existing_type=sa.String(length=80), nullable=True
        )
        batch.alter_column(
            "email", existing_type=sa.String(length=255), nullable=True
        )
        batch.alter_column(
            "name", existing_type=sa.String(length=120), nullable=True
        )
        batch.create_check_constraint(
            RECIPIENT_CHECK,
            "(username IS NULL AND email IS NULL AND name IS NULL) OR "
            "(username IS NOT NULL AND email IS NOT NULL AND name IS NOT NULL)",
        )


def downgrade() -> None:
    """Revoke generic invitations before restoring required recipient fields."""
    with op.batch_alter_table("workspace_invitations") as batch:
        batch.drop_constraint(RECIPIENT_CHECK, type_="check")
    op.execute(
        sa.text(
            """
            UPDATE workspace_invitations
            SET accepted_at = COALESCE(accepted_at, CURRENT_TIMESTAMP),
                username = 'revoked-generic-' || id,
                email = 'revoked-generic-' || id || '@invalid.local',
                name = 'Revoked generic invitation'
            WHERE username IS NULL
            """
        )
    )
    with op.batch_alter_table("workspace_invitations") as batch:
        batch.alter_column(
            "username", existing_type=sa.String(length=80), nullable=False
        )
        batch.alter_column(
            "email", existing_type=sa.String(length=255), nullable=False
        )
        batch.alter_column(
            "name", existing_type=sa.String(length=120), nullable=False
        )
