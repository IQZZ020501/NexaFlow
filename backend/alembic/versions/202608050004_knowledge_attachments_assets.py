"""knowledge attachments and assets

Revision ID: 202608050004
Revises: 202608050003
Create Date: 2026-08-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608050004"
down_revision: str | None = "202608050003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('available', 'consumed', 'deleted')",
            name="ck_knowledge_attachments_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_attachments_knowledge_workspace",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_knowledge_attachments_scope_id",
        ),
    )
    for column in ("workspace_id", "knowledge_base_id", "created_by_user_id"):
        op.create_index(
            op.f(f"ix_knowledge_attachments_{column}"),
            "knowledge_attachments",
            [column],
            unique=False,
        )

    op.add_column(
        "knowledge_documents",
        sa.Column("attachment_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        op.f("ix_knowledge_documents_attachment_id"),
        "knowledge_documents",
        ["attachment_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_knowledge_documents_attachment",
        "knowledge_documents",
        ["attachment_id"],
    )
    op.create_foreign_key(
        "fk_knowledge_documents_attachment_scope",
        "knowledge_documents",
        "knowledge_attachments",
        ["workspace_id", "knowledge_base_id", "attachment_id"],
        ["workspace_id", "knowledge_base_id", "id"],
    )

    op.create_table(
        "knowledge_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("asset_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("alt_text", sa.String(length=500), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('image')", name="ck_knowledge_assets_kind"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            name="fk_knowledge_assets_document_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint(
            "document_id",
            "asset_index",
            name="uq_knowledge_assets_document_index",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "document_id",
            "id",
            name="uq_knowledge_assets_scope_id",
        ),
    )
    for column in ("workspace_id", "knowledge_base_id", "document_id"):
        op.create_index(
            op.f(f"ix_knowledge_assets_{column}"),
            "knowledge_assets",
            [column],
            unique=False,
        )

    op.create_unique_constraint(
        "uq_knowledge_document_chunks_scope_id",
        "knowledge_document_chunks",
        ["workspace_id", "knowledge_base_id", "document_id", "id"],
    )
    op.create_table(
        "knowledge_chunk_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("asset_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id", "asset_id"],
            [
                "knowledge_assets.workspace_id",
                "knowledge_assets.knowledge_base_id",
                "knowledge_assets.document_id",
                "knowledge_assets.id",
            ],
            name="fk_knowledge_chunk_assets_asset_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id", "chunk_id"],
            [
                "knowledge_document_chunks.workspace_id",
                "knowledge_document_chunks.knowledge_base_id",
                "knowledge_document_chunks.document_id",
                "knowledge_document_chunks.id",
            ],
            name="fk_knowledge_chunk_assets_chunk_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id", "asset_id", name="uq_knowledge_chunk_assets_pair"),
        sa.UniqueConstraint("chunk_id", "asset_index", name="uq_knowledge_chunk_assets_order"),
    )
    for column in ("workspace_id", "knowledge_base_id", "document_id", "chunk_id", "asset_id"):
        op.create_index(
            op.f(f"ix_knowledge_chunk_assets_{column}"),
            "knowledge_chunk_assets",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("knowledge_chunk_assets")
    op.drop_constraint(
        "uq_knowledge_document_chunks_scope_id",
        "knowledge_document_chunks",
        type_="unique",
    )
    op.drop_table("knowledge_assets")
    op.drop_constraint(
        "fk_knowledge_documents_attachment_scope",
        "knowledge_documents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_knowledge_documents_attachment",
        "knowledge_documents",
        type_="unique",
    )
    op.drop_index(
        op.f("ix_knowledge_documents_attachment_id"),
        table_name="knowledge_documents",
    )
    op.drop_column("knowledge_documents", "attachment_id")
    op.drop_table("knowledge_attachments")
