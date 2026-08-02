"""rename model and knowledge tables

Revision ID: 202607060003
Revises: 202607060002
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607060003"
down_revision: str | None = "202607060002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("model_registry_models", "model")
    op.rename_table("knowledge_bases", "knowledge")


def downgrade() -> None:
    op.rename_table("knowledge", "knowledge_bases")
    op.rename_table("model", "model_registry_models")
