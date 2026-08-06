"""durable knowledge storage cleanup jobs

Revision ID: 202608060001
Revises: 202608050004
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608060001"
down_revision: str | None = "202608050004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_storage_cleanups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            name="uq_knowledge_storage_cleanups_knowledge_base",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_storage_cleanups_workspace_id"),
        "knowledge_storage_cleanups",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_storage_cleanups_next_attempt_at"),
        "knowledge_storage_cleanups",
        ["next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("knowledge_storage_cleanups")
