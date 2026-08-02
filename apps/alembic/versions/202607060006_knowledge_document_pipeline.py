"""knowledge document pipeline

Revision ID: 202607060006
Revises: 202607060005
Create Date: 2026-07-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202607060006"
down_revision: str | None = "202607060005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("last_error", sa.Text(), nullable=True))

    op.create_table(
        "knowledge_document_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("vector_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('preview', 'indexed', 'index_failed')",
            name="ck_knowledge_document_chunks_status",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_document_chunks_knowledge_workspace",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_document_chunks_document_index",
        ),
    )
    op.create_index(
        op.f("ix_knowledge_document_chunks_document_id"),
        "knowledge_document_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_document_chunks_knowledge_base_id"),
        "knowledge_document_chunks",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_document_chunks_vector_id"),
        "knowledge_document_chunks",
        ["vector_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_document_chunks_workspace_id"),
        "knowledge_document_chunks",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("task_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("processed_items", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "task_type IN ('parse', 'index', 'rebuild_index')",
            name="ck_knowledge_tasks_task_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_knowledge_tasks_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_tasks_knowledge_workspace",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_tasks_created_by_user_id"),
        "knowledge_tasks",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_tasks_document_id"),
        "knowledge_tasks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_tasks_knowledge_base_id"),
        "knowledge_tasks",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(op.f("ix_knowledge_tasks_status"), "knowledge_tasks", ["status"], unique=False)
    op.create_index(
        op.f("ix_knowledge_tasks_task_type"),
        "knowledge_tasks",
        ["task_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_tasks_workspace_id"),
        "knowledge_tasks",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_tasks_workspace_id"), table_name="knowledge_tasks")
    op.drop_index(op.f("ix_knowledge_tasks_task_type"), table_name="knowledge_tasks")
    op.drop_index(op.f("ix_knowledge_tasks_status"), table_name="knowledge_tasks")
    op.drop_index(op.f("ix_knowledge_tasks_knowledge_base_id"), table_name="knowledge_tasks")
    op.drop_index(op.f("ix_knowledge_tasks_document_id"), table_name="knowledge_tasks")
    op.drop_index(op.f("ix_knowledge_tasks_created_by_user_id"), table_name="knowledge_tasks")
    op.drop_table("knowledge_tasks")

    op.drop_index(op.f("ix_knowledge_document_chunks_workspace_id"), table_name="knowledge_document_chunks")
    op.drop_index(op.f("ix_knowledge_document_chunks_vector_id"), table_name="knowledge_document_chunks")
    op.drop_index(op.f("ix_knowledge_document_chunks_knowledge_base_id"), table_name="knowledge_document_chunks")
    op.drop_index(op.f("ix_knowledge_document_chunks_document_id"), table_name="knowledge_document_chunks")
    op.drop_table("knowledge_document_chunks")

    op.drop_column("knowledge_documents", "last_error")
