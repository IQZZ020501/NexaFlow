"""Use pg_search BM25 ranking for knowledge keyword retrieval."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608160001"
down_revision: str | None = "202608150003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GIN_INDEX_NAME = "ix_knowledge_document_chunks_content_search"
BM25_INDEX_NAME = "ix_knowledge_document_chunks_bm25_search"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_search"))
    op.drop_index(GIN_INDEX_NAME, table_name="knowledge_document_chunks")
    op.execute(
        sa.text(
            f"""
            CREATE INDEX {BM25_INDEX_NAME}
            ON knowledge_document_chunks
            USING paradedb (
                id,
                (search_text::pdb.jieba),
                (workspace_id::pdb.literal),
                (knowledge_base_id::pdb.literal),
                (document_id::pdb.literal)
            )
            WITH (key_field = 'id')
            WHERE status = 'indexed'
            """
        )
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.drop_index(BM25_INDEX_NAME, table_name="knowledge_document_chunks")
    op.execute(
        sa.text(
            f"""
            CREATE INDEX {GIN_INDEX_NAME}
            ON knowledge_document_chunks
            USING GIN (to_tsvector('simple'::regconfig, search_text))
            WHERE status = 'indexed'
            """
        )
    )
