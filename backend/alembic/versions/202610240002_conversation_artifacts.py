"""Preserve output paths for restoring immutable conversation file versions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610240002"
down_revision: str | None = "202610240001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generated_artifacts", sa.Column("relative_path", sa.String(512), nullable=True)
    )


def downgrade() -> None:
    bind = op.get_bind()
    artifacts = sa.table("generated_artifacts", sa.column("relative_path"))
    if bind.scalar(
        sa.select(sa.func.count())
        .select_from(artifacts)
        .where(artifacts.c.relative_path.is_not(None))
    ):
        raise RuntimeError("Cannot remove saved conversation file paths.")
    op.drop_column("generated_artifacts", "relative_path")
