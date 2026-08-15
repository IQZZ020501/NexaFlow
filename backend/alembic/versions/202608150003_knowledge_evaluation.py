"""Add durable knowledge retrieval evaluation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608150003"
down_revision: str | None = "202608150002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_knowledge_tasks_task_type",
        "knowledge_tasks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_knowledge_tasks_task_type",
        "knowledge_tasks",
        "task_type IN ('parse', 'index', 'rebuild_index', 'evaluate')",
    )
    op.create_unique_constraint(
        "uq_knowledge_tasks_scope_id",
        "knowledge_tasks",
        ["workspace_id", "knowledge_base_id", "id"],
    )
    op.create_table(
        "knowledge_evaluation_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_points", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_evaluation_cases_knowledge_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_knowledge_evaluation_cases_scope_id",
        ),
    )
    op.create_index(
        "ix_knowledge_evaluation_cases_scope",
        "knowledge_evaluation_cases",
        ["workspace_id", "knowledge_base_id", "created_at"],
    )
    op.create_table(
        "knowledge_evaluation_expectations",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_evaluation_expectations_knowledge_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "case_id"],
            [
                "knowledge_evaluation_cases.workspace_id",
                "knowledge_evaluation_cases.knowledge_base_id",
                "knowledge_evaluation_cases.id",
            ],
            name="fk_knowledge_evaluation_expectations_case_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            name="fk_knowledge_evaluation_expectations_document_scope",
        ),
        sa.PrimaryKeyConstraint("case_id", "document_id"),
    )
    op.create_table(
        "knowledge_evaluation_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("returned_document_ids", sa.JSON(), nullable=False),
        sa.Column("returned_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("hit_at_k", sa.Integer(), nullable=False),
        sa.Column("recall_at_k", sa.Float(), nullable=False),
        sa.Column("reciprocal_rank", sa.Float(), nullable=False),
        sa.Column("ndcg_at_k", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_evaluation_results_knowledge_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "task_id"],
            [
                "knowledge_tasks.workspace_id",
                "knowledge_tasks.knowledge_base_id",
                "knowledge_tasks.id",
            ],
            name="fk_knowledge_evaluation_results_task_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "case_id"],
            [
                "knowledge_evaluation_cases.workspace_id",
                "knowledge_evaluation_cases.knowledge_base_id",
                "knowledge_evaluation_cases.id",
            ],
            name="fk_knowledge_evaluation_results_case_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "case_id",
            name="uq_knowledge_evaluation_results_task_case",
        ),
    )
    op.create_index(
        "ix_knowledge_evaluation_results_task",
        "knowledge_evaluation_results",
        ["workspace_id", "knowledge_base_id", "task_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_evaluation_results_task",
        table_name="knowledge_evaluation_results",
    )
    op.drop_table("knowledge_evaluation_results")
    op.drop_table("knowledge_evaluation_expectations")
    op.drop_index(
        "ix_knowledge_evaluation_cases_scope",
        table_name="knowledge_evaluation_cases",
    )
    op.drop_table("knowledge_evaluation_cases")
    op.drop_constraint(
        "uq_knowledge_tasks_scope_id",
        "knowledge_tasks",
        type_="unique",
    )
    op.drop_constraint(
        "ck_knowledge_tasks_task_type",
        "knowledge_tasks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_knowledge_tasks_task_type",
        "knowledge_tasks",
        "task_type IN ('parse', 'index', 'rebuild_index')",
    )
