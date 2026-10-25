"""Remove knowledge graph storage, imported records and derived indexes."""

import re
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from qdrant_client import QdrantClient

from alembic import op
from app.infra.config.settings import Settings

revision: str = "202610250001"
down_revision: str | None = "202610240002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _delete_profile_collections(settings: Settings) -> None:
    # This one-time cleanup stays in migration history, outside the runtime.
    client = (
        QdrantClient(location=":memory:")
        if settings.qdrant_url == ":memory:"
        else QdrantClient(
            url=settings.qdrant_url, api_key=settings.qdrant_api_key or None
        )
    )
    try:
        for collection in client.get_collections().collections:
            if re.fullmatch(r"kb_[0-9a-f]{32}_graph", collection.name):
                if not client.delete_collection(collection.name):
                    raise RuntimeError("Qdrant graph collection deletion failed.")
    finally:
        client.close()


def _delete_imports(bind: sa.Connection, settings: Settings) -> None:
    documents = sa.table(
        "knowledge_documents",
        sa.column("id"),
        sa.column("attachment_id"),
        sa.column("storage_path"),
        sa.column("meta", sa.JSON),
    )
    chunks = sa.table(
        "knowledge_document_chunks", sa.column("document_id"), sa.column("kind")
    )
    rows = (
        bind.execute(
            sa.select(documents).where(
                sa.or_(
                    documents.c.id.in_(
                        sa.select(chunks.c.document_id).where(
                            chunks.c.kind == "graph_record"
                        )
                    ),
                    documents.c.meta["import_mode"].as_string() == "graph",
                )
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return
    if settings.knowledge_storage_dir is None:
        raise RuntimeError("Knowledge storage is required to remove graph imports.")
    root = Path(settings.knowledge_storage_dir).resolve()
    for row in rows:
        keys = [row["storage_path"], (row["meta"] or {}).get("normalized_artifact_key")]
        for key in keys:
            if not key:
                continue
            target = (root / key).resolve()
            if target == root or root not in target.parents:
                raise RuntimeError(
                    "Graph import storage path escapes the storage root."
                )
            target.unlink(missing_ok=True)
            parent = target.parent
            while parent != root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
    ids = [row["id"] for row in rows]
    for name in (
        "knowledge_chunk_assets",
        "knowledge_assets",
        "knowledge_document_chunks",
        "knowledge_document_parent_chunks",
        "knowledge_evaluation_expectations",
        "knowledge_tasks",
    ):
        table = sa.table(name, sa.column("document_id"))
        bind.execute(table.delete().where(table.c.document_id.in_(ids)))
    bind.execute(documents.delete().where(documents.c.id.in_(ids)))
    attachment_ids = [row["attachment_id"] for row in rows if row["attachment_id"]]
    if attachment_ids:
        attachments = sa.table("knowledge_attachments", sa.column("id"))
        bind.execute(attachments.delete().where(attachments.c.id.in_(attachment_ids)))


def upgrade() -> None:
    settings = Settings.from_env(require_bootstrap=False)
    _delete_profile_collections(settings)
    op.drop_constraint(
        "fk_knowledge_active_graph_revision", "knowledge", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_knowledge_active_graph_schema", "knowledge", type_="foreignkey"
    )
    for table in (
        "knowledge_graph_review_items",
        "knowledge_graph_claim_evidence",
        "knowledge_graph_mentions",
        "knowledge_graph_aliases",
        "knowledge_graph_claims",
        "knowledge_graph_entities",
        "knowledge_graph_revision_changes",
        "knowledge_graph_revisions",
        "knowledge_graph_schemas",
        "knowledge_document_references",
    ):
        op.drop_table(table)
    _delete_imports(op.get_bind(), settings)
    op.execute(
        "DELETE FROM knowledge_tasks WHERE task_type IN ('graph_sync', 'graph_rebuild')"
    )
    op.drop_constraint("ck_knowledge_tasks_task_type", "knowledge_tasks", type_="check")
    op.create_check_constraint(
        "ck_knowledge_tasks_task_type",
        "knowledge_tasks",
        "task_type IN ('parse', 'index', 'rebuild_index', 'evaluate')",
    )
    op.drop_constraint(
        "ck_knowledge_document_chunks_kind", "knowledge_document_chunks", type_="check"
    )
    op.create_check_constraint(
        "ck_knowledge_document_chunks_kind",
        "knowledge_document_chunks",
        "kind IN ('document', 'qa')",
    )
    for column in (
        "graph_enabled",
        "active_graph_schema_id",
        "active_graph_revision_id",
        "graph_extraction_model_id",
    ):
        op.drop_column("knowledge", column)
    op.drop_column("knowledge_evaluation_cases", "graph_expectation")
    op.drop_column("knowledge_evaluation_results", "graph_metrics")


def downgrade() -> None:
    raise RuntimeError("Knowledge graph removal deletes data and cannot be reversed.")
