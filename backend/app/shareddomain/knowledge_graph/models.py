from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now


def _revision_foreign_key(column: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["workspace_id", "knowledge_base_id", column],
        [
            "knowledge_graph_revisions.workspace_id",
            "knowledge_graph_revisions.knowledge_base_id",
            "knowledge_graph_revisions.id",
        ],
        name=name,
    )


class KnowledgeGraphSchema(Base):
    __tablename__ = "knowledge_graph_schemas"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_kg_schemas_knowledge",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_kg_schemas_scope_id",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "version",
            name="uq_kg_schemas_version",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "schema_hash",
            name="uq_kg_schemas_hash",
        ),
        CheckConstraint("version > 0", name="ck_kg_schemas_version"),
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_kg_schemas_status",
        ),
        Index(
            "uq_kg_schemas_active",
            "knowledge_base_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", index=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KnowledgeGraphRevision(Base):
    __tablename__ = "knowledge_graph_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_kg_revisions_knowledge",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "schema_id"],
            [
                "knowledge_graph_schemas.workspace_id",
                "knowledge_graph_schemas.knowledge_base_id",
                "knowledge_graph_schemas.id",
            ],
            name="fk_kg_revisions_schema",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "parent_revision_id"],
            [
                "knowledge_graph_revisions.workspace_id",
                "knowledge_graph_revisions.knowledge_base_id",
                "knowledge_graph_revisions.id",
            ],
            name="fk_kg_revisions_parent",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_kg_revisions_scope_id",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "revision_no",
            name="uq_kg_revisions_number",
        ),
        CheckConstraint("revision_no > 0", name="ck_kg_revisions_number"),
        CheckConstraint(
            "status IN ('building', 'published', 'failed', 'retired')",
            name="ck_kg_revisions_status",
        ),
        Index(
            "uq_kg_revisions_published",
            "knowledge_base_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    parent_revision_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="building", index=True
    )
    source_watermark: Mapped[str] = mapped_column(
        String(255), nullable=False, default=""
    )
    stats_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    model_usage_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KnowledgeGraphRevisionChange(Base):
    __tablename__ = "knowledge_graph_revision_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_kg_changes_knowledge",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "revision_id"],
            [
                "knowledge_graph_revisions.workspace_id",
                "knowledge_graph_revisions.knowledge_base_id",
                "knowledge_graph_revisions.id",
            ],
            name="fk_kg_changes_revision",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_kg_changes_scope_id",
        ),
        UniqueConstraint(
            "revision_id",
            "record_kind",
            "record_key",
            name="uq_kg_changes_record",
        ),
        UniqueConstraint(
            "revision_id",
            "sequence_no",
            name="uq_kg_changes_sequence",
        ),
        CheckConstraint("sequence_no >= 0", name="ck_kg_changes_sequence"),
        CheckConstraint(
            "record_kind IN ('entity', 'alias', 'mention', 'claim', 'evidence', 'review')",
            name="ck_kg_changes_kind",
        ),
        CheckConstraint(
            "operation IN ('upsert', 'retire', 'delete')",
            name="ck_kg_changes_operation",
        ),
        Index(
            "ix_kg_changes_revision_sequence",
            "workspace_id",
            "knowledge_base_id",
            "revision_id",
            "sequence_no",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    record_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(
        String(20), nullable=False, default="upsert"
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KnowledgeGraphEntity(Base):
    __tablename__ = "knowledge_graph_entities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_kg_entities_knowledge",
            ondelete="CASCADE",
        ),
        _revision_foreign_key("created_revision_id", "fk_kg_entities_created_revision"),
        _revision_foreign_key(
            "last_published_revision_id",
            "fk_kg_entities_published_revision",
        ),
        _revision_foreign_key("retired_revision_id", "fk_kg_entities_retired_revision"),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_kg_entities_scope_id",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "entity_type",
            "external_key",
            name="uq_kg_entities_external_key",
        ),
        CheckConstraint("degree >= 0", name="ck_kg_entities_degree"),
        CheckConstraint(
            "state IN ('active', 'merged', 'retired')",
            name="ck_kg_entities_state",
        ),
        Index(
            "ix_kg_entities_identity",
            "workspace_id",
            "knowledge_base_id",
            "entity_type",
            "normalized_name",
        ),
        Index(
            "ix_kg_entities_component",
            "workspace_id",
            "knowledge_base_id",
            "component_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    external_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    properties_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    profile_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    profile_claim_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    component_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    degree: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )
    created_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    last_published_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    retired_revision_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KnowledgeGraphAlias(Base):
    __tablename__ = "knowledge_graph_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_kg_aliases_knowledge",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "entity_id"],
            [
                "knowledge_graph_entities.workspace_id",
                "knowledge_graph_entities.knowledge_base_id",
                "knowledge_graph_entities.id",
            ],
            name="fk_kg_aliases_entity",
            ondelete="CASCADE",
        ),
        _revision_foreign_key("created_revision_id", "fk_kg_aliases_created_revision"),
        _revision_foreign_key(
            "last_published_revision_id",
            "fk_kg_aliases_published_revision",
        ),
        _revision_foreign_key("retired_revision_id", "fk_kg_aliases_retired_revision"),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_kg_aliases_scope_id",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "entity_id",
            "normalized_alias",
            name="uq_kg_aliases_entity_value",
        ),
        Index(
            "ix_kg_aliases_lookup",
            "workspace_id",
            "knowledge_base_id",
            "normalized_alias",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="generated"
    )
    created_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    last_published_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    retired_revision_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KnowledgeGraphMention(Base):
    __tablename__ = "knowledge_graph_mentions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_kg_mentions_knowledge",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "entity_id"],
            [
                "knowledge_graph_entities.workspace_id",
                "knowledge_graph_entities.knowledge_base_id",
                "knowledge_graph_entities.id",
            ],
            name="fk_kg_mentions_entity",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
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
        _revision_foreign_key("created_revision_id", "fk_kg_mentions_created_revision"),
        _revision_foreign_key(
            "last_published_revision_id",
            "fk_kg_mentions_published_revision",
        ),
        _revision_foreign_key("retired_revision_id", "fk_kg_mentions_retired_revision"),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_kg_mentions_scope_id",
        ),
        UniqueConstraint(
            "entity_id",
            "chunk_id",
            "start_offset",
            "end_offset",
            name="uq_kg_mentions_position",
        ),
        CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_kg_mentions_offsets",
        ),
        Index(
            "ix_kg_mentions_document",
            "workspace_id",
            "knowledge_base_id",
            "document_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    surface_text: Mapped[str] = mapped_column(String(500), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_method: Mapped[str] = mapped_column(String(40), nullable=False)
    created_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    last_published_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    retired_revision_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KnowledgeGraphClaim(Base):
    __tablename__ = "knowledge_graph_claims"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_kg_claims_knowledge",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "subject_entity_id"],
            [
                "knowledge_graph_entities.workspace_id",
                "knowledge_graph_entities.knowledge_base_id",
                "knowledge_graph_entities.id",
            ],
            name="fk_kg_claims_subject",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "object_entity_id"],
            [
                "knowledge_graph_entities.workspace_id",
                "knowledge_graph_entities.knowledge_base_id",
                "knowledge_graph_entities.id",
            ],
            name="fk_kg_claims_object",
        ),
        _revision_foreign_key("created_revision_id", "fk_kg_claims_created_revision"),
        _revision_foreign_key(
            "last_published_revision_id",
            "fk_kg_claims_published_revision",
        ),
        _revision_foreign_key("retired_revision_id", "fk_kg_claims_retired_revision"),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_kg_claims_scope_id",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "fingerprint",
            name="uq_kg_claims_fingerprint",
        ),
        CheckConstraint(
            "((object_entity_id IS NOT NULL AND object_value_json IS NULL) OR "
            "(object_entity_id IS NULL AND object_value_json IS NOT NULL))",
            name="ck_kg_claims_object",
        ),
        CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1",
            name="ck_kg_claims_quality",
        ),
        CheckConstraint("support_count >= 0", name="ck_kg_claims_support"),
        CheckConstraint(
            "status IN ('candidate', 'active', 'rejected', 'superseded')",
            name="ck_kg_claims_status",
        ),
        Index(
            "ix_kg_claims_subject",
            "workspace_id",
            "knowledge_base_id",
            "subject_entity_id",
            "predicate",
        ),
        Index(
            "ix_kg_claims_object",
            "workspace_id",
            "knowledge_base_id",
            "object_entity_id",
            "predicate",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    subject_entity_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    predicate: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    object_entity_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    object_value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    properties_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="candidate", index=True
    )
    source_kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="explicit_text"
    )
    quality_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    last_published_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    retired_revision_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KnowledgeGraphClaimEvidence(Base):
    __tablename__ = "knowledge_graph_claim_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_kg_evidence_knowledge",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "claim_id"],
            [
                "knowledge_graph_claims.workspace_id",
                "knowledge_graph_claims.knowledge_base_id",
                "knowledge_graph_claims.id",
            ],
            name="fk_kg_evidence_claim",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
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
        _revision_foreign_key("created_revision_id", "fk_kg_evidence_created_revision"),
        _revision_foreign_key(
            "last_published_revision_id",
            "fk_kg_evidence_published_revision",
        ),
        _revision_foreign_key("retired_revision_id", "fk_kg_evidence_retired_revision"),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_kg_evidence_scope_id",
        ),
        UniqueConstraint(
            "claim_id",
            "chunk_id",
            "start_offset",
            "end_offset",
            name="uq_kg_evidence_position",
        ),
        CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_kg_evidence_offsets",
        ),
        CheckConstraint(
            "evidence_state IN ('active', 'deleted', 'inaccessible')",
            name="ck_kg_evidence_state",
        ),
        Index(
            "ix_kg_evidence_claim_state",
            "workspace_id",
            "knowledge_base_id",
            "claim_id",
            "evidence_state",
        ),
        Index(
            "ix_kg_evidence_document",
            "workspace_id",
            "knowledge_base_id",
            "document_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    claim_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    extractor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    evidence_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )
    created_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    last_published_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    retired_revision_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KnowledgeGraphReviewItem(Base):
    __tablename__ = "knowledge_graph_review_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_kg_reviews_knowledge",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "revision_id"],
            [
                "knowledge_graph_revisions.workspace_id",
                "knowledge_graph_revisions.knowledge_base_id",
                "knowledge_graph_revisions.id",
            ],
            name="fk_kg_reviews_revision",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_kg_reviews_scope_id",
        ),
        CheckConstraint(
            "kind IN ('ambiguous_entity', 'possible_duplicate', 'implicit_relation', "
            "'conflict', 'schema_violation', 'orphan')",
            name="ck_kg_reviews_kind",
        ),
        CheckConstraint(
            "status IN ('open', 'approved', 'rejected', 'resolved')",
            name="ck_kg_reviews_status",
        ),
        Index(
            "ix_kg_reviews_queue",
            "workspace_id",
            "knowledge_base_id",
            "status",
            "kind",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True
    )
    decision_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
