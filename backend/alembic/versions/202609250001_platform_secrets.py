"""Store deployment signing and encryption keys once per installation.

``JWT_SECRET_KEY`` and ``MODEL_SECRET_KEY`` were environment-only values, so a
regenerated or lost ``.env`` invalidated every session and orphaned stored
ciphertext. ``platform_secrets`` now holds one row per key: the application
creates a missing row on first start from the environment value (or a generated
value) and then always reads the stored key.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609250001"
down_revision: str | None = "202609230001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_secrets",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(value) > 0", name="ck_platform_secrets_value"),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    secrets = sa.Table("platform_secrets", sa.MetaData(), autoload_with=bind)
    if bind.scalar(sa.select(sa.func.count()).select_from(secrets)):
        raise RuntimeError(
            "Cannot downgrade while stored deployment keys exist: dropping them "
            "makes every stored credential and session unreadable. Copy the values "
            "into JWT_SECRET_KEY/MODEL_SECRET_KEY first."
        )
    op.drop_table("platform_secrets")
