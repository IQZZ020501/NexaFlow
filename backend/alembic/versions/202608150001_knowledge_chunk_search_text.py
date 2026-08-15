"""Add enriched knowledge chunk search text."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608150001"
down_revision: str | None = "202608140001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_knowledge_document_chunks_content_search"


def upgrade() -> None:
    with op.batch_alter_table("knowledge_document_chunks") as batch:
        batch.add_column(
            sa.Column(
                "kind",
                sa.String(length=20),
                nullable=False,
                server_default="document",
            )
        )
        batch.add_column(
            sa.Column("search_text", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column(
                "meta",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.create_check_constraint(
            "ck_knowledge_document_chunks_kind",
            "kind IN ('document', 'qa')",
        )

    op.execute(sa.text("UPDATE knowledge_document_chunks SET search_text = content"))
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index(INDEX_NAME, table_name="knowledge_document_chunks")
        op.execute(
            f"""
            CREATE INDEX {INDEX_NAME}
            ON knowledge_document_chunks
            USING GIN (to_tsvector('simple'::regconfig, search_text))
            WHERE status = 'indexed'
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index(INDEX_NAME, table_name="knowledge_document_chunks")

    with op.batch_alter_table("knowledge_document_chunks") as batch:
        batch.drop_constraint(
            "ck_knowledge_document_chunks_kind",
            type_="check",
        )
        batch.drop_column("meta")
        batch.drop_column("search_text")
        batch.drop_column("kind")

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            f"""
            CREATE INDEX {INDEX_NAME}
            ON knowledge_document_chunks
            USING GIN (to_tsvector('simple'::regconfig, content))
            WHERE status = 'indexed'
            """
        )
