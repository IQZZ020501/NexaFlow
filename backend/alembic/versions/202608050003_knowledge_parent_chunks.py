"""knowledge parent chunks

Revision ID: 202608050003
Revises: 202608050002
Create Date: 2026-08-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608050003"
down_revision: str | None = "202608050002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_SCOPE_UNIQUE = "uq_knowledge_documents_workspace_knowledge_id"
CHUNK_DOCUMENT_SCOPE_FK = "fk_knowledge_document_chunks_document_scope"
CHUNK_PARENT_SCOPE_FK = "fk_knowledge_document_chunks_parent_scope"
CHUNK_PARENT_OFFSETS_CHECK = "ck_knowledge_document_chunks_parent_offsets"


def upgrade() -> None:
    op.create_unique_constraint(
        DOCUMENT_SCOPE_UNIQUE,
        "knowledge_documents",
        ["workspace_id", "knowledge_base_id", "id"],
    )
    op.create_table(
        "knowledge_document_parent_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("parent_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_document_parent_chunks_knowledge_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            name="fk_knowledge_document_parent_chunks_document_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "parent_index",
            name="uq_knowledge_document_parent_chunks_document_index",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "document_id",
            "id",
            name="uq_knowledge_document_parent_chunks_scope_id",
        ),
    )
    for column in ("workspace_id", "knowledge_base_id", "document_id"):
        op.create_index(
            op.f(f"ix_knowledge_document_parent_chunks_{column}"),
            "knowledge_document_parent_chunks",
            [column],
            unique=False,
        )

    op.add_column(
        "knowledge_document_chunks",
        sa.Column("parent_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "knowledge_document_chunks",
        sa.Column("start_offset", sa.Integer(), nullable=True),
    )
    op.add_column(
        "knowledge_document_chunks",
        sa.Column("end_offset", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_knowledge_document_chunks_parent_id"),
        "knowledge_document_chunks",
        ["parent_id"],
        unique=False,
    )
    op.create_foreign_key(
        CHUNK_DOCUMENT_SCOPE_FK,
        "knowledge_document_chunks",
        "knowledge_documents",
        ["workspace_id", "knowledge_base_id", "document_id"],
        ["workspace_id", "knowledge_base_id", "id"],
    )
    op.create_foreign_key(
        CHUNK_PARENT_SCOPE_FK,
        "knowledge_document_chunks",
        "knowledge_document_parent_chunks",
        ["workspace_id", "knowledge_base_id", "document_id", "parent_id"],
        ["workspace_id", "knowledge_base_id", "document_id", "id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        CHUNK_PARENT_OFFSETS_CHECK,
        "knowledge_document_chunks",
        "(parent_id IS NULL AND start_offset IS NULL AND end_offset IS NULL) OR "
        "(parent_id IS NOT NULL AND start_offset IS NOT NULL AND end_offset IS NOT NULL "
        "AND start_offset >= 0 AND end_offset > start_offset)",
    )


def downgrade() -> None:
    op.drop_constraint(
        CHUNK_PARENT_OFFSETS_CHECK,
        "knowledge_document_chunks",
        type_="check",
    )
    op.drop_constraint(
        CHUNK_PARENT_SCOPE_FK,
        "knowledge_document_chunks",
        type_="foreignkey",
    )
    op.drop_constraint(
        CHUNK_DOCUMENT_SCOPE_FK,
        "knowledge_document_chunks",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_knowledge_document_chunks_parent_id"),
        table_name="knowledge_document_chunks",
    )
    op.drop_column("knowledge_document_chunks", "end_offset")
    op.drop_column("knowledge_document_chunks", "start_offset")
    op.drop_column("knowledge_document_chunks", "parent_id")

    for column in ("document_id", "knowledge_base_id", "workspace_id"):
        op.drop_index(
            op.f(f"ix_knowledge_document_parent_chunks_{column}"),
            table_name="knowledge_document_parent_chunks",
        )
    op.drop_table("knowledge_document_parent_chunks")
    op.drop_constraint(
        DOCUMENT_SCOPE_UNIQUE,
        "knowledge_documents",
        type_="unique",
    )
