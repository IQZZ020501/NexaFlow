"""Add deterministic knowledge document references."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608150002"
down_revision: str | None = "202608150001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_document_references",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("source_document_id", sa.String(length=36), nullable=False),
        sa.Column("source_chunk_id", sa.String(length=36), nullable=False),
        sa.Column("target_document_id", sa.String(length=36), nullable=True),
        sa.Column("target_parent_id", sa.String(length=36), nullable=True),
        sa.Column("target_label", sa.String(length=255), nullable=False),
        sa.Column(
            "target_section",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
        sa.Column("reference_type", sa.String(length=20), nullable=False),
        sa.Column("source_ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reference_type IN ('markdown', 'text')",
            name="ck_knowledge_document_references_type",
        ),
        sa.CheckConstraint(
            "source_ordinal >= 0",
            name="ck_knowledge_document_references_source_ordinal",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_document_references_knowledge_workspace",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "knowledge_base_id",
                "source_document_id",
                "source_chunk_id",
            ],
            [
                "knowledge_document_chunks.workspace_id",
                "knowledge_document_chunks.knowledge_base_id",
                "knowledge_document_chunks.document_id",
                "knowledge_document_chunks.id",
            ],
            name="fk_knowledge_document_references_source_chunk_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "target_document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            name="fk_knowledge_document_references_target_document_scope",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "knowledge_base_id",
                "target_document_id",
                "target_parent_id",
            ],
            [
                "knowledge_document_parent_chunks.workspace_id",
                "knowledge_document_parent_chunks.knowledge_base_id",
                "knowledge_document_parent_chunks.document_id",
                "knowledge_document_parent_chunks.id",
            ],
            name="fk_knowledge_document_references_target_parent_scope",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_chunk_id",
            "target_label",
            "target_section",
            name="uq_knowledge_document_references_source_label",
        ),
    )
    op.create_index(
        "ix_knowledge_document_references_source_scope",
        "knowledge_document_references",
        ["workspace_id", "knowledge_base_id", "source_chunk_id"],
    )
    op.create_index(
        "ix_knowledge_document_references_target_document",
        "knowledge_document_references",
        ["workspace_id", "knowledge_base_id", "target_document_id"],
    )
    op.create_index(
        "ix_knowledge_document_references_target_label",
        "knowledge_document_references",
        ["workspace_id", "knowledge_base_id", "target_label", "target_document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_document_references_target_label",
        table_name="knowledge_document_references",
    )
    op.drop_index(
        "ix_knowledge_document_references_target_document",
        table_name="knowledge_document_references",
    )
    op.drop_index(
        "ix_knowledge_document_references_source_scope",
        table_name="knowledge_document_references",
    )
    op.drop_table("knowledge_document_references")
