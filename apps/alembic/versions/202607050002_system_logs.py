"""system logs

Revision ID: 202607050002
Revises: 202607050001
Create Date: 2026-07-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202607050002"
down_revision: str | None = "202607050001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("event", sa.String(length=80), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=True),
        sa.Column("method", sa.String(length=12), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("username", sa.String(length=80), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_logs_event"), "system_logs", ["event"], unique=False)
    op.create_index(op.f("ix_system_logs_level"), "system_logs", ["level"], unique=False)
    op.create_index(op.f("ix_system_logs_path"), "system_logs", ["path"], unique=False)
    op.create_index(
        op.f("ix_system_logs_status_code"),
        "system_logs",
        ["status_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_logs_user_id"),
        "system_logs",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_system_logs_user_id"), table_name="system_logs")
    op.drop_index(op.f("ix_system_logs_status_code"), table_name="system_logs")
    op.drop_index(op.f("ix_system_logs_path"), table_name="system_logs")
    op.drop_index(op.f("ix_system_logs_level"), table_name="system_logs")
    op.drop_index(op.f("ix_system_logs_event"), table_name="system_logs")
    op.drop_table("system_logs")
