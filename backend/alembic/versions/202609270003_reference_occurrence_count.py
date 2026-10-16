"""Preserve repeated document link occurrences."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609270003"
down_revision: str | None = "202609270002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_document_references",
        sa.Column(
            "occurrence_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "ck_knowledge_document_references_occurrence_count",
        "knowledge_document_references",
        "occurrence_count >= 1",
    )
    op.drop_constraint(
        "uq_knowledge_document_references_source_label",
        "knowledge_document_references",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_knowledge_document_references_source_label",
        "knowledge_document_references",
        [
            "source_chunk_id",
            "target_label",
            "target_section",
            "reference_type",
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    references = sa.table(
        "knowledge_document_references",
        sa.column("id", sa.String(length=36)),
        sa.column("source_chunk_id", sa.String(length=36)),
        sa.column("target_label", sa.String(length=255)),
        sa.column("target_section", sa.String(length=500)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    ranked = sa.select(
        references.c.id,
        sa.func.row_number()
        .over(
            partition_by=(
                references.c.source_chunk_id,
                references.c.target_label,
                references.c.target_section,
            ),
            order_by=(references.c.created_at, references.c.id),
        )
        .label("position"),
    ).subquery()
    bind.execute(
        sa.delete(references).where(
            references.c.id.in_(
                sa.select(ranked.c.id).where(ranked.c.position > 1)
            )
        )
    )
    op.drop_constraint(
        "uq_knowledge_document_references_source_label",
        "knowledge_document_references",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_knowledge_document_references_source_label",
        "knowledge_document_references",
        ["source_chunk_id", "target_label", "target_section"],
    )
    op.drop_constraint(
        "ck_knowledge_document_references_occurrence_count",
        "knowledge_document_references",
        type_="check",
    )
    op.drop_column("knowledge_document_references", "occurrence_count")
