"""Add persistent evidence graph storage."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608200007"
down_revision: str | None = "202608200006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTITY_BM25_INDEX = "ix_knowledge_graph_entities_bm25_search"


def _scope_columns() -> tuple[sa.Column, sa.Column, sa.Column]:
    return (
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
    )


def _workspace_foreign_key() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"])


def _knowledge_foreign_key(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "knowledge_base_id"],
        ["knowledge.workspace_id", "knowledge.id"],
        name=name,
        ondelete="CASCADE",
    )


def _scope_unique(name: str) -> sa.UniqueConstraint:
    return sa.UniqueConstraint("workspace_id", "knowledge_base_id", "id", name=name)


def _revision_foreign_key(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", "knowledge_base_id", column],
        [
            "knowledge_graph_revisions.workspace_id",
            "knowledge_graph_revisions.knowledge_base_id",
            "knowledge_graph_revisions.id",
        ],
        name=name,
    )


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _create_scope_indexes(table_name: str) -> None:
    op.create_index(op.f(f"ix_{table_name}_workspace_id"), table_name, ["workspace_id"])
    op.create_index(
        op.f(f"ix_{table_name}_knowledge_base_id"),
        table_name,
        ["knowledge_base_id"],
    )


def upgrade() -> None:
    op.create_table(
        "knowledge_graph_schemas",
        *_scope_columns(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_json", sa.JSON(), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        *_timestamps(),
        _workspace_foreign_key(),
        _knowledge_foreign_key("fk_kg_schemas_knowledge"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        _scope_unique("uq_kg_schemas_scope_id"),
        sa.UniqueConstraint(
            "knowledge_base_id", "version", name="uq_kg_schemas_version"
        ),
        sa.UniqueConstraint(
            "knowledge_base_id", "schema_hash", name="uq_kg_schemas_hash"
        ),
        sa.CheckConstraint("version > 0", name="ck_kg_schemas_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_kg_schemas_status",
        ),
    )
    _create_scope_indexes("knowledge_graph_schemas")
    op.create_index(
        op.f("ix_knowledge_graph_schemas_created_by_user_id"),
        "knowledge_graph_schemas",
        ["created_by_user_id"],
    )
    op.create_index(
        op.f("ix_knowledge_graph_schemas_status"),
        "knowledge_graph_schemas",
        ["status"],
    )
    op.create_index(
        "uq_kg_schemas_active",
        "knowledge_graph_schemas",
        ["knowledge_base_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "knowledge_graph_revisions",
        *_scope_columns(),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("schema_id", sa.String(length=36), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_watermark", sa.String(length=255), nullable=False),
        sa.Column("stats_json", sa.JSON(), nullable=False),
        sa.Column("model_usage_json", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _workspace_foreign_key(),
        _knowledge_foreign_key("fk_kg_revisions_knowledge"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "schema_id"],
            [
                "knowledge_graph_schemas.workspace_id",
                "knowledge_graph_schemas.knowledge_base_id",
                "knowledge_graph_schemas.id",
            ],
            name="fk_kg_revisions_schema",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "parent_revision_id"],
            [
                "knowledge_graph_revisions.workspace_id",
                "knowledge_graph_revisions.knowledge_base_id",
                "knowledge_graph_revisions.id",
            ],
            name="fk_kg_revisions_parent",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        _scope_unique("uq_kg_revisions_scope_id"),
        sa.UniqueConstraint(
            "knowledge_base_id", "revision_no", name="uq_kg_revisions_number"
        ),
        sa.CheckConstraint("revision_no > 0", name="ck_kg_revisions_number"),
        sa.CheckConstraint(
            "status IN ('building', 'published', 'failed', 'retired')",
            name="ck_kg_revisions_status",
        ),
    )
    _create_scope_indexes("knowledge_graph_revisions")
    for column in (
        "schema_id",
        "parent_revision_id",
        "status",
        "created_by_user_id",
    ):
        op.create_index(
            op.f(f"ix_knowledge_graph_revisions_{column}"),
            "knowledge_graph_revisions",
            [column],
        )
    op.create_index(
        "uq_kg_revisions_published",
        "knowledge_graph_revisions",
        ["knowledge_base_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )

    op.create_table(
        "knowledge_graph_revision_changes",
        *_scope_columns(),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("record_kind", sa.String(length=20), nullable=False),
        sa.Column("record_key", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _workspace_foreign_key(),
        _knowledge_foreign_key("fk_kg_changes_knowledge"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "revision_id"],
            [
                "knowledge_graph_revisions.workspace_id",
                "knowledge_graph_revisions.knowledge_base_id",
                "knowledge_graph_revisions.id",
            ],
            name="fk_kg_changes_revision",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        _scope_unique("uq_kg_changes_scope_id"),
        sa.UniqueConstraint(
            "revision_id",
            "record_kind",
            "record_key",
            name="uq_kg_changes_record",
        ),
        sa.UniqueConstraint(
            "revision_id", "sequence_no", name="uq_kg_changes_sequence"
        ),
        sa.CheckConstraint("sequence_no >= 0", name="ck_kg_changes_sequence"),
        sa.CheckConstraint(
            "record_kind IN ('entity', 'alias', 'mention', 'claim', 'evidence', 'review')",
            name="ck_kg_changes_kind",
        ),
        sa.CheckConstraint(
            "operation IN ('upsert', 'retire', 'delete')",
            name="ck_kg_changes_operation",
        ),
    )
    _create_scope_indexes("knowledge_graph_revision_changes")
    op.create_index(
        "ix_kg_changes_revision_sequence",
        "knowledge_graph_revision_changes",
        ["workspace_id", "knowledge_base_id", "revision_id", "sequence_no"],
    )

    op.create_table(
        "knowledge_graph_entities",
        *_scope_columns(),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("canonical_name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("external_key", sa.String(length=500), nullable=True),
        sa.Column("properties_json", sa.JSON(), nullable=False),
        sa.Column("profile_markdown", sa.Text(), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_claim_ids", sa.JSON(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("component_id", sa.String(length=64), nullable=True),
        sa.Column("degree", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("created_revision_id", sa.String(length=36), nullable=False),
        sa.Column("last_published_revision_id", sa.String(length=36), nullable=False),
        sa.Column("retired_revision_id", sa.String(length=36), nullable=True),
        *_timestamps(),
        _workspace_foreign_key(),
        _knowledge_foreign_key("fk_kg_entities_knowledge"),
        _revision_foreign_key(
            "created_revision_id", "fk_kg_entities_created_revision"
        ),
        _revision_foreign_key(
            "last_published_revision_id", "fk_kg_entities_published_revision"
        ),
        _revision_foreign_key(
            "retired_revision_id", "fk_kg_entities_retired_revision"
        ),
        sa.PrimaryKeyConstraint("id"),
        _scope_unique("uq_kg_entities_scope_id"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "entity_type",
            "external_key",
            name="uq_kg_entities_external_key",
        ),
        sa.CheckConstraint("degree >= 0", name="ck_kg_entities_degree"),
        sa.CheckConstraint(
            "state IN ('active', 'merged', 'retired')",
            name="ck_kg_entities_state",
        ),
    )
    _create_scope_indexes("knowledge_graph_entities")
    for column in (
        "entity_type",
        "component_id",
        "state",
        "created_revision_id",
        "last_published_revision_id",
        "retired_revision_id",
    ):
        op.create_index(
            op.f(f"ix_knowledge_graph_entities_{column}"),
            "knowledge_graph_entities",
            [column],
        )
    op.create_index(
        "ix_kg_entities_identity",
        "knowledge_graph_entities",
        ["workspace_id", "knowledge_base_id", "entity_type", "normalized_name"],
    )
    op.create_index(
        "ix_kg_entities_component",
        "knowledge_graph_entities",
        ["workspace_id", "knowledge_base_id", "component_id"],
    )

    op.create_table(
        "knowledge_graph_aliases",
        *_scope_columns(),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.String(length=500), nullable=False),
        sa.Column("normalized_alias", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_revision_id", sa.String(length=36), nullable=False),
        sa.Column("last_published_revision_id", sa.String(length=36), nullable=False),
        sa.Column("retired_revision_id", sa.String(length=36), nullable=True),
        *_timestamps(),
        _workspace_foreign_key(),
        _knowledge_foreign_key("fk_kg_aliases_knowledge"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "entity_id"],
            [
                "knowledge_graph_entities.workspace_id",
                "knowledge_graph_entities.knowledge_base_id",
                "knowledge_graph_entities.id",
            ],
            name="fk_kg_aliases_entity",
            ondelete="CASCADE",
        ),
        _revision_foreign_key(
            "created_revision_id", "fk_kg_aliases_created_revision"
        ),
        _revision_foreign_key(
            "last_published_revision_id", "fk_kg_aliases_published_revision"
        ),
        _revision_foreign_key(
            "retired_revision_id", "fk_kg_aliases_retired_revision"
        ),
        sa.PrimaryKeyConstraint("id"),
        _scope_unique("uq_kg_aliases_scope_id"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "entity_id",
            "normalized_alias",
            name="uq_kg_aliases_entity_value",
        ),
    )
    _create_scope_indexes("knowledge_graph_aliases")
    for column in (
        "entity_id",
        "created_revision_id",
        "last_published_revision_id",
        "retired_revision_id",
    ):
        op.create_index(
            op.f(f"ix_knowledge_graph_aliases_{column}"),
            "knowledge_graph_aliases",
            [column],
        )
    op.create_index(
        "ix_kg_aliases_lookup",
        "knowledge_graph_aliases",
        ["workspace_id", "knowledge_base_id", "normalized_alias"],
    )

    op.create_table(
        "knowledge_graph_mentions",
        *_scope_columns(),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("surface_text", sa.String(length=500), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("resolution_method", sa.String(length=40), nullable=False),
        sa.Column("created_revision_id", sa.String(length=36), nullable=False),
        sa.Column("last_published_revision_id", sa.String(length=36), nullable=False),
        sa.Column("retired_revision_id", sa.String(length=36), nullable=True),
        *_timestamps(),
        _workspace_foreign_key(),
        _knowledge_foreign_key("fk_kg_mentions_knowledge"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "entity_id"],
            [
                "knowledge_graph_entities.workspace_id",
                "knowledge_graph_entities.knowledge_base_id",
                "knowledge_graph_entities.id",
            ],
            name="fk_kg_mentions_entity",
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
            name="fk_kg_mentions_chunk",
            ondelete="CASCADE",
        ),
        _revision_foreign_key(
            "created_revision_id", "fk_kg_mentions_created_revision"
        ),
        _revision_foreign_key(
            "last_published_revision_id", "fk_kg_mentions_published_revision"
        ),
        _revision_foreign_key(
            "retired_revision_id", "fk_kg_mentions_retired_revision"
        ),
        sa.PrimaryKeyConstraint("id"),
        _scope_unique("uq_kg_mentions_scope_id"),
        sa.UniqueConstraint(
            "entity_id",
            "chunk_id",
            "start_offset",
            "end_offset",
            name="uq_kg_mentions_position",
        ),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_kg_mentions_offsets",
        ),
    )
    _create_scope_indexes("knowledge_graph_mentions")
    for column in (
        "entity_id",
        "document_id",
        "chunk_id",
        "created_revision_id",
        "last_published_revision_id",
        "retired_revision_id",
    ):
        op.create_index(
            op.f(f"ix_knowledge_graph_mentions_{column}"),
            "knowledge_graph_mentions",
            [column],
        )
    op.create_index(
        "ix_kg_mentions_document",
        "knowledge_graph_mentions",
        ["workspace_id", "knowledge_base_id", "document_id"],
    )

    op.create_table(
        "knowledge_graph_claims",
        *_scope_columns(),
        sa.Column("subject_entity_id", sa.String(length=36), nullable=False),
        sa.Column("predicate", sa.String(length=80), nullable=False),
        sa.Column("object_entity_id", sa.String(length=36), nullable=True),
        sa.Column(
            "object_value_json",
            sa.JSON(none_as_null=True),
            nullable=True,
        ),
        sa.Column("properties_json", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("support_count", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_revision_id", sa.String(length=36), nullable=False),
        sa.Column("last_published_revision_id", sa.String(length=36), nullable=False),
        sa.Column("retired_revision_id", sa.String(length=36), nullable=True),
        *_timestamps(),
        _workspace_foreign_key(),
        _knowledge_foreign_key("fk_kg_claims_knowledge"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "subject_entity_id"],
            [
                "knowledge_graph_entities.workspace_id",
                "knowledge_graph_entities.knowledge_base_id",
                "knowledge_graph_entities.id",
            ],
            name="fk_kg_claims_subject",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "object_entity_id"],
            [
                "knowledge_graph_entities.workspace_id",
                "knowledge_graph_entities.knowledge_base_id",
                "knowledge_graph_entities.id",
            ],
            name="fk_kg_claims_object",
        ),
        _revision_foreign_key(
            "created_revision_id", "fk_kg_claims_created_revision"
        ),
        _revision_foreign_key(
            "last_published_revision_id", "fk_kg_claims_published_revision"
        ),
        _revision_foreign_key(
            "retired_revision_id", "fk_kg_claims_retired_revision"
        ),
        sa.PrimaryKeyConstraint("id"),
        _scope_unique("uq_kg_claims_scope_id"),
        sa.UniqueConstraint(
            "knowledge_base_id", "fingerprint", name="uq_kg_claims_fingerprint"
        ),
        sa.CheckConstraint(
            "((object_entity_id IS NOT NULL AND object_value_json IS NULL) OR "
            "(object_entity_id IS NULL AND object_value_json IS NOT NULL))",
            name="ck_kg_claims_object",
        ),
        sa.CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1",
            name="ck_kg_claims_quality",
        ),
        sa.CheckConstraint("support_count >= 0", name="ck_kg_claims_support"),
        sa.CheckConstraint(
            "status IN ('candidate', 'active', 'rejected', 'superseded')",
            name="ck_kg_claims_status",
        ),
    )
    _create_scope_indexes("knowledge_graph_claims")
    for column in (
        "subject_entity_id",
        "predicate",
        "object_entity_id",
        "status",
        "created_revision_id",
        "last_published_revision_id",
        "retired_revision_id",
    ):
        op.create_index(
            op.f(f"ix_knowledge_graph_claims_{column}"),
            "knowledge_graph_claims",
            [column],
        )
    op.create_index(
        "ix_kg_claims_subject",
        "knowledge_graph_claims",
        ["workspace_id", "knowledge_base_id", "subject_entity_id", "predicate"],
    )
    op.create_index(
        "ix_kg_claims_object",
        "knowledge_graph_claims",
        ["workspace_id", "knowledge_base_id", "object_entity_id", "predicate"],
    )

    op.create_table(
        "knowledge_graph_claim_evidence",
        *_scope_columns(),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("extractor_type", sa.String(length=40), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_state", sa.String(length=20), nullable=False),
        sa.Column("created_revision_id", sa.String(length=36), nullable=False),
        sa.Column("last_published_revision_id", sa.String(length=36), nullable=False),
        sa.Column("retired_revision_id", sa.String(length=36), nullable=True),
        *_timestamps(),
        _workspace_foreign_key(),
        _knowledge_foreign_key("fk_kg_evidence_knowledge"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "claim_id"],
            [
                "knowledge_graph_claims.workspace_id",
                "knowledge_graph_claims.knowledge_base_id",
                "knowledge_graph_claims.id",
            ],
            name="fk_kg_evidence_claim",
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
            name="fk_kg_evidence_chunk",
            ondelete="CASCADE",
        ),
        _revision_foreign_key(
            "created_revision_id", "fk_kg_evidence_created_revision"
        ),
        _revision_foreign_key(
            "last_published_revision_id", "fk_kg_evidence_published_revision"
        ),
        _revision_foreign_key(
            "retired_revision_id", "fk_kg_evidence_retired_revision"
        ),
        sa.PrimaryKeyConstraint("id"),
        _scope_unique("uq_kg_evidence_scope_id"),
        sa.UniqueConstraint(
            "claim_id",
            "chunk_id",
            "start_offset",
            "end_offset",
            name="uq_kg_evidence_position",
        ),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_kg_evidence_offsets",
        ),
        sa.CheckConstraint(
            "evidence_state IN ('active', 'deleted', 'inaccessible')",
            name="ck_kg_evidence_state",
        ),
    )
    _create_scope_indexes("knowledge_graph_claim_evidence")
    for column in (
        "claim_id",
        "document_id",
        "chunk_id",
        "evidence_state",
        "created_revision_id",
        "last_published_revision_id",
        "retired_revision_id",
    ):
        op.create_index(
            op.f(f"ix_knowledge_graph_claim_evidence_{column}"),
            "knowledge_graph_claim_evidence",
            [column],
        )
    op.create_index(
        "ix_kg_evidence_claim_state",
        "knowledge_graph_claim_evidence",
        ["workspace_id", "knowledge_base_id", "claim_id", "evidence_state"],
    )
    op.create_index(
        "ix_kg_evidence_document",
        "knowledge_graph_claim_evidence",
        ["workspace_id", "knowledge_base_id", "document_id"],
    )

    op.create_table(
        "knowledge_graph_review_items",
        *_scope_columns(),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _workspace_foreign_key(),
        _knowledge_foreign_key("fk_kg_reviews_knowledge"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "revision_id"],
            [
                "knowledge_graph_revisions.workspace_id",
                "knowledge_graph_revisions.knowledge_base_id",
                "knowledge_graph_revisions.id",
            ],
            name="fk_kg_reviews_revision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        _scope_unique("uq_kg_reviews_scope_id"),
        sa.CheckConstraint(
            "kind IN ('ambiguous_entity', 'possible_duplicate', 'implicit_relation', "
            "'conflict', 'schema_violation', 'orphan')",
            name="ck_kg_reviews_kind",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'approved', 'rejected', 'resolved')",
            name="ck_kg_reviews_status",
        ),
    )
    _create_scope_indexes("knowledge_graph_review_items")
    for column in (
        "kind",
        "status",
        "revision_id",
        "created_by_user_id",
        "reviewed_by_user_id",
    ):
        op.create_index(
            op.f(f"ix_knowledge_graph_review_items_{column}"),
            "knowledge_graph_review_items",
            [column],
        )
    op.create_index(
        "ix_kg_reviews_queue",
        "knowledge_graph_review_items",
        ["workspace_id", "knowledge_base_id", "status", "kind", "created_at"],
    )

    with op.batch_alter_table("knowledge") as batch:
        batch.add_column(
            sa.Column(
                "graph_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("active_graph_schema_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(
            sa.Column("active_graph_revision_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "graph_extraction_model_id", sa.String(length=36), nullable=True
            )
        )
        batch.create_foreign_key(
            "fk_knowledge_graph_extraction_model",
            "model",
            ["graph_extraction_model_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_knowledge_active_graph_schema",
            "knowledge_graph_schemas",
            ["workspace_id", "id", "active_graph_schema_id"],
            ["workspace_id", "knowledge_base_id", "id"],
            deferrable=True,
            initially="DEFERRED",
        )
        batch.create_foreign_key(
            "fk_knowledge_active_graph_revision",
            "knowledge_graph_revisions",
            ["workspace_id", "id", "active_graph_revision_id"],
            ["workspace_id", "knowledge_base_id", "id"],
            deferrable=True,
            initially="DEFERRED",
        )
        for column in (
            "active_graph_schema_id",
            "active_graph_revision_id",
            "graph_extraction_model_id",
        ):
            batch.create_index(op.f(f"ix_knowledge_{column}"), [column])

    with op.batch_alter_table("knowledge_tasks") as batch:
        batch.drop_constraint("ck_knowledge_tasks_task_type", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_tasks_task_type",
            "task_type IN ('parse', 'index', 'rebuild_index', 'evaluate', "
            "'graph_sync', 'graph_rebuild')",
        )

    with op.batch_alter_table("knowledge_document_chunks") as batch:
        batch.drop_constraint("ck_knowledge_document_chunks_kind", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_document_chunks_kind",
            "kind IN ('document', 'qa', 'graph_record')",
        )

    with op.batch_alter_table("knowledge_evaluation_cases") as batch:
        batch.add_column(
            sa.Column(
                "graph_expectation",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
    with op.batch_alter_table("knowledge_evaluation_results") as batch:
        batch.add_column(
            sa.Column(
                "graph_metrics",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                f"""
                CREATE INDEX {ENTITY_BM25_INDEX}
                ON knowledge_graph_entities
                USING paradedb (
                    id,
                    (search_text::pdb.jieba),
                    (workspace_id::pdb.literal),
                    (knowledge_base_id::pdb.literal),
                    (entity_type::pdb.literal),
                    (state::pdb.literal)
                )
                WITH (key_field = 'id')
                WHERE state = 'active' AND retired_revision_id IS NULL
                """
            )
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index(ENTITY_BM25_INDEX, table_name="knowledge_graph_entities")

    with op.batch_alter_table("knowledge_evaluation_results") as batch:
        batch.drop_column("graph_metrics")
    with op.batch_alter_table("knowledge_evaluation_cases") as batch:
        batch.drop_column("graph_expectation")

    with op.batch_alter_table("knowledge_document_chunks") as batch:
        batch.drop_constraint("ck_knowledge_document_chunks_kind", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_document_chunks_kind",
            "kind IN ('document', 'qa')",
        )

    with op.batch_alter_table("knowledge_tasks") as batch:
        batch.drop_constraint("ck_knowledge_tasks_task_type", type_="check")
        batch.create_check_constraint(
            "ck_knowledge_tasks_task_type",
            "task_type IN ('parse', 'index', 'rebuild_index', 'evaluate')",
        )

    with op.batch_alter_table("knowledge") as batch:
        batch.drop_constraint(
            "fk_knowledge_active_graph_revision", type_="foreignkey"
        )
        batch.drop_constraint("fk_knowledge_active_graph_schema", type_="foreignkey")
        batch.drop_constraint(
            "fk_knowledge_graph_extraction_model", type_="foreignkey"
        )
        for column in (
            "graph_extraction_model_id",
            "active_graph_revision_id",
            "active_graph_schema_id",
        ):
            batch.drop_index(op.f(f"ix_knowledge_{column}"))
            batch.drop_column(column)
        batch.drop_column("graph_enabled")

    op.drop_table("knowledge_graph_review_items")
    op.drop_table("knowledge_graph_claim_evidence")
    op.drop_table("knowledge_graph_claims")
    op.drop_table("knowledge_graph_mentions")
    op.drop_table("knowledge_graph_aliases")
    op.drop_table("knowledge_graph_entities")
    op.drop_table("knowledge_graph_revision_changes")
    op.drop_index(
        "uq_kg_revisions_published", table_name="knowledge_graph_revisions"
    )
    op.drop_table("knowledge_graph_revisions")
    op.drop_index("uq_kg_schemas_active", table_name="knowledge_graph_schemas")
    op.drop_table("knowledge_graph_schemas")
