from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now
from app.entities.workflows import workflow_upload_expires_at


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_workflow_definitions_agent_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint("agent_id", name="uq_workflow_definitions_agent_id"),
        UniqueConstraint(
            "workspace_id", "id", name="uq_workflow_definitions_workspace_id"
        ),
        CheckConstraint("revision >= 1", name="ck_workflow_definitions_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_workflow_versions_agent_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "definition_id"],
            ["workflow_definitions.workspace_id", "workflow_definitions.id"],
            name="fk_workflow_versions_definition_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "agent_id", "version_number", name="uq_workflow_versions_agent_number"
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_workflow_versions_workspace_id"
        ),
        CheckConstraint("version_number >= 1", name="ck_workflow_versions_number"),
        CheckConstraint(
            "definition_revision >= 1", name="ck_workflow_versions_revision"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    definition_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    definition_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    default_model_id: Mapped[str] = mapped_column(
        ForeignKey("model.id"), nullable=False, index=True
    )
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resource_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkflowRunDetail(Base):
    __tablename__ = "workflow_run_details"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_workflow_run_details_run_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "definition_id"],
            ["workflow_definitions.workspace_id", "workflow_definitions.id"],
            name="fk_workflow_run_details_definition_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "version_id"],
            ["workflow_versions.workspace_id", "workflow_versions.id"],
            name="fk_workflow_run_details_version_workspace",
        ),
        UniqueConstraint("run_id", name="uq_workflow_run_details_run_id"),
        CheckConstraint(
            "source IN ('draft', 'published')", name="ck_workflow_run_details_source"
        ),
        CheckConstraint("max_steps > 0", name="ck_workflow_run_details_max_steps"),
        CheckConstraint(
            "max_model_tokens > 0", name="ck_workflow_run_details_max_tokens"
        ),
        CheckConstraint("step_count >= 0", name="ck_workflow_run_details_steps"),
        CheckConstraint("token_usage >= 0", name="ck_workflow_run_details_tokens"),
        CheckConstraint(
            "(source = 'draft' AND version_id IS NULL AND version_number IS NULL) OR "
            "(source = 'published' AND version_id IS NOT NULL AND version_number IS NOT NULL)",
            name="ck_workflow_run_details_version_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    definition_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    definition_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resource_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resource_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_model_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_usage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WorkflowNodeExecution(Base):
    __tablename__ = "workflow_node_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_workflow_node_executions_run_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "run_id", "node_id", name="uq_workflow_node_executions_run_node"
        ),
        CheckConstraint(
            "status IN ('running', 'awaiting_input', 'succeeded', 'failed', 'skipped')",
            name="ck_workflow_node_executions_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(80), nullable=False)
    node_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    model_usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WorkflowUpload(Base):
    __tablename__ = "workflow_uploads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_workflow_uploads_agent_workspace",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "category IN ('document', 'image', 'audio')",
            name="ck_workflow_uploads_category",
        ),
        CheckConstraint("size_bytes > 0", name="ck_workflow_uploads_size"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    uploaded_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=workflow_upload_expires_at,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkflowUploadStorageCleanup(Base):
    __tablename__ = "workflow_upload_storage_cleanups"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_workflow_upload_cleanups_size"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # No foreign keys: the retry record must survive user, Agent, and workspace deletion.
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    uploaded_by_user_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
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
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
