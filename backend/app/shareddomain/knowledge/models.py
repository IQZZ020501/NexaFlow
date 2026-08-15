from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now


class KnowledgeBase(Base):
    __tablename__ = "knowledge"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_knowledge_base_workspace_name"),
        UniqueConstraint("workspace_id", "id", name="uq_knowledge_base_workspace_id"),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_knowledge_bases_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    embedding_model_id: Mapped[str | None] = mapped_column(
        ForeignKey("model.id"),
        nullable=True,
        index=True,
    )
    reranker_model_id: Mapped[str | None] = mapped_column(
        ForeignKey("model.id"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeAttachment(Base):
    __tablename__ = "knowledge_attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_attachments_knowledge_workspace",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_knowledge_attachments_scope_id",
        ),
        CheckConstraint(
            "status IN ('available', 'consumed', 'deleted')",
            name="ck_knowledge_attachments_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_documents_knowledge_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "attachment_id"],
            [
                "knowledge_attachments.workspace_id",
                "knowledge_attachments.knowledge_base_id",
                "knowledge_attachments.id",
            ],
            name="fk_knowledge_documents_attachment_scope",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_knowledge_documents_workspace_knowledge_id",
        ),
        UniqueConstraint("attachment_id", name="uq_knowledge_documents_attachment"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    attachment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="application/octet-stream",
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeAsset(Base):
    __tablename__ = "knowledge_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            name="fk_knowledge_assets_document_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "document_id",
            "id",
            name="uq_knowledge_assets_scope_id",
        ),
        UniqueConstraint(
            "document_id",
            "asset_index",
            name="uq_knowledge_assets_document_index",
        ),
        CheckConstraint("kind IN ('image')", name="ck_knowledge_assets_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    asset_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="image")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    alt_text: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeDocumentParentChunk(Base):
    __tablename__ = "knowledge_document_parent_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_document_parent_chunks_knowledge_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            name="fk_knowledge_document_parent_chunks_document_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "document_id",
            "parent_index",
            name="uq_knowledge_document_parent_chunks_document_index",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "document_id",
            "id",
            name="uq_knowledge_document_parent_chunks_scope_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    parent_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeDocumentChunk(Base):
    __tablename__ = "knowledge_document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_document_chunks_knowledge_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            name="fk_knowledge_document_chunks_document_scope",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id", "parent_id"],
            [
                "knowledge_document_parent_chunks.workspace_id",
                "knowledge_document_parent_chunks.knowledge_base_id",
                "knowledge_document_parent_chunks.document_id",
                "knowledge_document_parent_chunks.id",
            ],
            name="fk_knowledge_document_chunks_parent_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_knowledge_document_chunks_document_index",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "document_id",
            "id",
            name="uq_knowledge_document_chunks_scope_id",
        ),
        CheckConstraint(
            "status IN ('preview', 'indexed', 'index_failed')",
            name="ck_knowledge_document_chunks_status",
        ),
        CheckConstraint(
            "kind IN ('document', 'qa')",
            name="ck_knowledge_document_chunks_kind",
        ),
        CheckConstraint(
            "(parent_id IS NULL AND start_offset IS NULL AND end_offset IS NULL) OR "
            "(parent_id IS NOT NULL AND start_offset IS NOT NULL AND end_offset IS NOT NULL "
            "AND start_offset >= 0 AND end_offset > start_offset)",
            name="ck_knowledge_document_chunks_parent_offsets",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="document")
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="preview")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeDocumentReference(Base):
    __tablename__ = "knowledge_document_references"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_document_references_knowledge_workspace",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "knowledge_base_id",
                "source_document_id",
                "source_chunk_id",
            ],
            [
                "knowledge_document_chunks.workspace_id",
                "knowledge_document_chunks.knowledge_base_id",
                "knowledge_document_chunks.document_id",
                "knowledge_document_chunks.id",
            ],
            name="fk_knowledge_document_references_source_chunk_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "target_document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            name="fk_knowledge_document_references_target_document_scope",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "knowledge_base_id",
                "target_document_id",
                "target_parent_id",
            ],
            [
                "knowledge_document_parent_chunks.workspace_id",
                "knowledge_document_parent_chunks.knowledge_base_id",
                "knowledge_document_parent_chunks.document_id",
                "knowledge_document_parent_chunks.id",
            ],
            name="fk_knowledge_document_references_target_parent_scope",
        ),
        UniqueConstraint(
            "source_chunk_id",
            "target_label",
            "target_section",
            name="uq_knowledge_document_references_source_label",
        ),
        CheckConstraint(
            "reference_type IN ('markdown', 'text')",
            name="ck_knowledge_document_references_type",
        ),
        CheckConstraint(
            "source_ordinal >= 0",
            name="ck_knowledge_document_references_source_ordinal",
        ),
        CheckConstraint(
            "target_parent_id IS NULL OR target_document_id IS NOT NULL",
            name="ck_knowledge_document_references_parent_requires_document",
        ),
        Index(
            "ix_knowledge_document_references_source_scope",
            "workspace_id",
            "knowledge_base_id",
            "source_chunk_id",
        ),
        Index(
            "ix_knowledge_document_references_target_document",
            "workspace_id",
            "knowledge_base_id",
            "target_document_id",
        ),
        Index(
            "ix_knowledge_document_references_target_label",
            "workspace_id",
            "knowledge_base_id",
            "target_label",
            "target_document_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False
    )
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_chunk_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_label: Mapped[str] = mapped_column(String(255), nullable=False)
    target_section: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    reference_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class KnowledgeChunkAsset(Base):
    __tablename__ = "knowledge_chunk_assets"
    __table_args__ = (
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        UniqueConstraint("chunk_id", "asset_id", name="uq_knowledge_chunk_assets_pair"),
        UniqueConstraint("chunk_id", "asset_index", name="uq_knowledge_chunk_assets_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    asset_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeTask(Base):
    __tablename__ = "knowledge_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_tasks_knowledge_workspace",
        ),
        CheckConstraint(
            "task_type IN ('parse', 'index', 'rebuild_index', 'evaluate')",
            name="ck_knowledge_tasks_task_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_knowledge_tasks_status",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_knowledge_tasks_scope_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeEvaluationCase(Base):
    __tablename__ = "knowledge_evaluation_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_evaluation_cases_knowledge_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "knowledge_base_id",
            "id",
            name="uq_knowledge_evaluation_cases_scope_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_points: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class KnowledgeEvaluationExpectation(Base):
    __tablename__ = "knowledge_evaluation_expectations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_evaluation_expectations_knowledge_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "case_id"],
            [
                "knowledge_evaluation_cases.workspace_id",
                "knowledge_evaluation_cases.knowledge_base_id",
                "knowledge_evaluation_cases.id",
            ],
            name="fk_knowledge_evaluation_expectations_case_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "document_id"],
            [
                "knowledge_documents.workspace_id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.id",
            ],
            name="fk_knowledge_evaluation_expectations_document_scope",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeEvaluationResult(Base):
    __tablename__ = "knowledge_evaluation_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_knowledge_evaluation_results_knowledge_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "task_id"],
            [
                "knowledge_tasks.workspace_id",
                "knowledge_tasks.knowledge_base_id",
                "knowledge_tasks.id",
            ],
            name="fk_knowledge_evaluation_results_task_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id", "case_id"],
            [
                "knowledge_evaluation_cases.workspace_id",
                "knowledge_evaluation_cases.knowledge_base_id",
                "knowledge_evaluation_cases.id",
            ],
            name="fk_knowledge_evaluation_results_case_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "task_id",
            "case_id",
            name="uq_knowledge_evaluation_results_task_case",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    returned_document_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    returned_chunk_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    hit_at_k: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recall_at_k: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reciprocal_rank: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ndcg_at_k: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trace: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeStorageCleanup(Base):
    __tablename__ = "knowledge_storage_cleanups"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            name="uq_knowledge_storage_cleanups_knowledge_base",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # No foreign keys: the retry record must survive workspace and knowledge deletion.
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
