"""knowledge chunk full text search

Revision ID: 202608050001
Revises: 202608040004
Create Date: 2026-08-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608050001"
down_revision: str | None = "202608040004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_knowledge_document_chunks_content_search"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"""
        CREATE INDEX {INDEX_NAME}
        ON knowledge_document_chunks
        USING GIN (to_tsvector('simple'::regconfig, content))
        WHERE status = 'indexed'
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_index(INDEX_NAME, table_name="knowledge_document_chunks")
