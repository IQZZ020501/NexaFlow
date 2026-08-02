"""knowledge model settings

Revision ID: 202607060005
Revises: 202607060004
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202607060005"
down_revision: str | None = "202607060004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge",
        sa.Column("embedding_model_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "knowledge",
        sa.Column("reranker_model_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        op.f("ix_knowledge_embedding_model_id"),
        "knowledge",
        ["embedding_model_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_reranker_model_id"),
        "knowledge",
        ["reranker_model_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_knowledge_embedding_model",
        "knowledge",
        "model",
        ["embedding_model_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_knowledge_reranker_model",
        "knowledge",
        "model",
        ["reranker_model_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_knowledge_reranker_model", "knowledge", type_="foreignkey")
    op.drop_constraint("fk_knowledge_embedding_model", "knowledge", type_="foreignkey")
    op.drop_index(op.f("ix_knowledge_reranker_model_id"), table_name="knowledge")
    op.drop_index(op.f("ix_knowledge_embedding_model_id"), table_name="knowledge")
    op.drop_column("knowledge", "reranker_model_id")
    op.drop_column("knowledge", "embedding_model_id")
