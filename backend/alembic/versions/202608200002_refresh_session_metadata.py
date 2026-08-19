"""Track refresh-session device metadata and revocation state."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608200002"
down_revision: str | None = "202608200001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_sessions", sa.Column("user_agent", sa.String(length=512), nullable=True))
    op.add_column("refresh_sessions", sa.Column("ip_address", sa.String(length=64), nullable=True))
    op.add_column(
        "refresh_sessions",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "refresh_sessions",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE refresh_sessions SET last_used_at = created_at WHERE last_used_at IS NULL"))
    with op.batch_alter_table("refresh_sessions") as batch:
        batch.alter_column("last_used_at", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("refresh_sessions") as batch:
        batch.drop_column("revoked_at")
        batch.drop_column("last_used_at")
        batch.drop_column("ip_address")
        batch.drop_column("user_agent")
