from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    column,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now
from app.shareddomain.resource_folders.models import ResourceFolder  # noqa: F401

AGENT_RUN_QUEUED_STATUS = "queued"
AGENT_RUN_PLANNING_STATUS = "planning"
AGENT_RUN_PLANNED_STATUS = "planned"
AGENT_RUN_RUNNING_STATUS = "running"
AGENT_RUN_AWAITING_APPROVAL_STATUS = "awaiting_approval"
AGENT_RUN_AWAITING_INPUT_STATUS = "awaiting_input"
AGENT_RUN_AWAITING_CHILD_STATUS = "awaiting_child"
AGENT_RUN_SUCCEEDED_STATUS = "succeeded"
AGENT_RUN_FAILED_STATUS = "failed"
AGENT_RUN_CANCELLED_STATUS = "cancelled"
AGENT_RUN_UNIFIED_QUEUED_STATUS = "queued_v2"
AGENT_RUN_UNIFIED_RUNNING_STATUS = "running_v2"
AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS = "awaiting_approval_v2"
AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS = "awaiting_input_v2"
AGENT_RUN_UNIFIED_AWAITING_CHILD_STATUS = "awaiting_child_v2"
AGENT_RUN_LEGACY_CLAIMABLE_STATUSES = (
    AGENT_RUN_QUEUED_STATUS,
    AGENT_RUN_RUNNING_STATUS,
)
AGENT_RUN_UNIFIED_CLAIMABLE_STATUSES = (
    AGENT_RUN_UNIFIED_QUEUED_STATUS,
    AGENT_RUN_UNIFIED_RUNNING_STATUS,
)
AGENT_RUN_RUNNING_STATUSES = (
    AGENT_RUN_RUNNING_STATUS,
    AGENT_RUN_UNIFIED_RUNNING_STATUS,
)
AGENT_RUN_AWAITING_APPROVAL_STATUSES = (
    AGENT_RUN_AWAITING_APPROVAL_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS,
)
AGENT_RUN_AWAITING_INPUT_STATUSES = (
    AGENT_RUN_AWAITING_INPUT_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS,
)
AGENT_RUN_AWAITING_CHILD_STATUSES = (
    AGENT_RUN_AWAITING_CHILD_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_CHILD_STATUS,
)
AGENT_RUN_ACTIVE_STATUSES = (
    AGENT_RUN_QUEUED_STATUS,
    AGENT_RUN_PLANNING_STATUS,
    AGENT_RUN_PLANNED_STATUS,
    AGENT_RUN_RUNNING_STATUS,
    AGENT_RUN_AWAITING_APPROVAL_STATUS,
    AGENT_RUN_AWAITING_INPUT_STATUS,
    AGENT_RUN_AWAITING_CHILD_STATUS,
    AGENT_RUN_UNIFIED_QUEUED_STATUS,
    AGENT_RUN_UNIFIED_RUNNING_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_CHILD_STATUS,
)


def is_unified_agent_run_status(value: str) -> bool:
    return value in {
        AGENT_RUN_UNIFIED_QUEUED_STATUS,
        AGENT_RUN_UNIFIED_RUNNING_STATUS,
        AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS,
        AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS,
        AGENT_RUN_UNIFIED_AWAITING_CHILD_STATUS,
    }


def agent_run_display_status(value: str) -> str:
    return {
        AGENT_RUN_UNIFIED_QUEUED_STATUS: AGENT_RUN_QUEUED_STATUS,
        AGENT_RUN_UNIFIED_RUNNING_STATUS: AGENT_RUN_RUNNING_STATUS,
        AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS: AGENT_RUN_AWAITING_APPROVAL_STATUS,
        AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS: AGENT_RUN_AWAITING_INPUT_STATUS,
        AGENT_RUN_UNIFIED_AWAITING_CHILD_STATUS: AGENT_RUN_AWAITING_CHILD_STATUS,
    }.get(value, value)


def agent_run_storage_statuses(value: str) -> tuple[str, ...]:
    """Return every persisted status represented by one public status."""
    return {
        AGENT_RUN_QUEUED_STATUS: (
            AGENT_RUN_QUEUED_STATUS,
            AGENT_RUN_UNIFIED_QUEUED_STATUS,
        ),
        AGENT_RUN_RUNNING_STATUS: (
            AGENT_RUN_RUNNING_STATUS,
            AGENT_RUN_UNIFIED_RUNNING_STATUS,
        ),
        AGENT_RUN_AWAITING_APPROVAL_STATUS: (
            AGENT_RUN_AWAITING_APPROVAL_STATUS,
            AGENT_RUN_UNIFIED_AWAITING_APPROVAL_STATUS,
        ),
        AGENT_RUN_AWAITING_INPUT_STATUS: (
            AGENT_RUN_AWAITING_INPUT_STATUS,
            AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS,
        ),
        AGENT_RUN_AWAITING_CHILD_STATUS: (
            AGENT_RUN_AWAITING_CHILD_STATUS,
            AGENT_RUN_UNIFIED_AWAITING_CHILD_STATUS,
        ),
    }.get(value, (value,))


def agent_run_generation(configuration_source: str) -> str:
    return "unified" if configuration_source in {"draft", "published"} else "legacy"


def queued_agent_run_status(generation: str) -> str:
    return (
        AGENT_RUN_UNIFIED_QUEUED_STATUS
        if generation == "unified"
        else AGENT_RUN_QUEUED_STATUS
    )


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "folder_id"],
            ["resource_folders.workspace_id", "resource_folders.id"],
            name="fk_agents_folder_workspace",
        ),
        UniqueConstraint("workspace_id", "name", name="uq_agents_workspace_name"),
        UniqueConstraint("workspace_id", "id", name="uq_agents_workspace_id"),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_agents_status",
        ),
        CheckConstraint(
            "knowledge_query_mode IN ('required', 'agentic')",
            name="ck_agents_knowledge_query_mode",
        ),
        CheckConstraint(
            "app_type IN ('agent', 'workflow')",
            name="ck_agents_app_type",
        ),
        CheckConstraint(
            "(published = false AND published_by_user_id IS NULL AND published_at IS NULL) "
            "OR (published = true AND published_by_user_id IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_agents_publication",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    folder_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    app_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="agent", server_default="agent"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    interaction_config: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(ForeignKey("model.id"), nullable=False, index=True)
    knowledge_query_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="required", server_default="required"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    current_published_version_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", name="fk_agents_published_by_user_id"),
        nullable=True,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentPublicationVersion(Base):
    __tablename__ = "agent_publication_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_publication_versions_agent_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "agent_id",
            "version_number",
            name="uq_agent_publication_versions_agent_number",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_agent_publication_versions_workspace_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "agent_id",
            "id",
            name="uq_agent_publication_versions_workspace_agent_id",
        ),
        CheckConstraint(
            "version_number >= 1", name="ck_agent_publication_versions_number"
        ),
        CheckConstraint(
            "schema_version >= 1", name="ck_agent_publication_versions_schema"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resource_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentKnowledgeBase(Base):
    __tablename__ = "agent_knowledge_bases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_knowledge_bases_agent_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "knowledge_base_id"],
            ["knowledge.workspace_id", "knowledge.id"],
            name="fk_agent_knowledge_bases_knowledge_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "agent_id",
            "knowledge_base_id",
            name="uq_agent_knowledge_bases_binding",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentMcpTool(Base):
    __tablename__ = "agent_mcp_tools"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_mcp_tools_agent_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "mcp_server_id"],
            ["mcp_servers.workspace_id", "mcp_servers.id"],
            name="fk_agent_mcp_tools_server_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "agent_id",
            "mcp_server_id",
            "tool_name",
            name="uq_agent_mcp_tools_binding",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    mcp_server_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentApiCredential(Base):
    __tablename__ = "agent_api_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_api_credentials_agent_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "token_hash",
            name="uq_agent_api_credentials_token_hash",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hint: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_runs_agent_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "root_run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_agent_runs_root_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "parent_run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_agent_runs_parent_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "regenerated_from_run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_agent_runs_regenerated_from",
            ondelete="SET NULL",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_agent_runs_workspace_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "agent_id",
            name="uq_agent_runs_workspace_agent_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "agent_id",
            "access_source",
            "consumer_id",
            "conversation_id",
            name="uq_agent_runs_state_identity",
        ),
        UniqueConstraint(
            "parent_run_id",
            "parent_node_id",
            name="uq_agent_runs_parent_node",
        ),
        CheckConstraint(
            "(depth = 0 AND parent_run_id IS NULL AND parent_node_id IS NULL "
            "AND root_run_id = id) OR "
            "(depth = 1 AND parent_run_id IS NOT NULL AND parent_node_id IS NOT NULL "
            "AND root_run_id = parent_run_id)",
            name="ck_agent_runs_parent_depth",
        ),
        CheckConstraint(
            "access_source IN ('console', 'public', 'api')",
            name="ck_agent_runs_access_source",
        ),
        CheckConstraint(
            "feedback IS NULL OR feedback IN ('positive', 'negative')",
            name="ck_agent_runs_feedback",
        ),
        CheckConstraint(
            "(access_source = 'console' AND requested_by_user_id IS NOT NULL "
            "AND consumer_id = requested_by_user_id "
            "AND execution_user_id = requested_by_user_id) OR "
            "(access_source IN ('public', 'api') AND requested_by_user_id IS NULL)",
            name="ck_agent_runs_access_identity",
        ),
        Index(
            "ix_agent_runs_conversation_id",
            "conversation_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requested_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    execution_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", name="fk_agent_runs_execution_user_id"),
        nullable=False,
        index=True,
    )
    access_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="console", server_default="console", index=True
    )
    consumer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), nullable=False, default=new_id
    )
    root_run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    parent_run_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    parent_node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    regenerated_from_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_context: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feedback_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trace_id: Mapped[str] = mapped_column(
        String(36), nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AgentRunState(Base):
    __tablename__ = "agent_run_states"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "workspace_id",
                "run_id",
                "agent_id",
                "access_source",
                "consumer_id",
                "conversation_id",
            ],
            [
                "agent_runs.workspace_id",
                "agent_runs.id",
                "agent_runs.agent_id",
                "agent_runs.access_source",
                "agent_runs.consumer_id",
                "agent_runs.conversation_id",
            ],
            name="fk_agent_run_states_run_identity",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('queued', 'planning', 'planned', 'running', 'awaiting_approval', 'awaiting_input', 'awaiting_child', 'queued_v2', 'running_v2', 'awaiting_approval_v2', 'awaiting_input_v2', 'awaiting_child_v2', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_run_states_status",
        ),
        CheckConstraint(
            "worker_generation IN ('legacy', 'unified')",
            name="ck_agent_run_states_generation",
        ),
        CheckConstraint(
            "(worker_generation = 'unified' AND status IN "
            "('queued_v2', 'running_v2', 'awaiting_approval_v2', "
            "'awaiting_input_v2', 'awaiting_child_v2', 'succeeded', 'failed', 'cancelled')) OR "
            "(worker_generation = 'legacy' AND status IN "
            "('queued', 'planning', 'planned', 'running', 'awaiting_approval', "
            "'awaiting_input', 'awaiting_child', 'succeeded', 'failed', 'cancelled'))",
            name="ck_agent_run_states_worker_generation",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="ck_agent_run_states_attempts",
        ),
        CheckConstraint(
            "state_version >= 1", name="ck_agent_run_states_version"
        ),
        CheckConstraint(
            "lease_expires_at IS NULL OR worker_task_id IS NOT NULL",
            name="ck_agent_run_states_lease",
        ),
        Index(
            "uq_agent_run_states_active_conversation",
            "workspace_id",
            "agent_id",
            "access_source",
            "consumer_id",
            "conversation_id",
            unique=True,
            postgresql_where=column("status").in_(AGENT_RUN_ACTIVE_STATUSES),
            sqlite_where=column("status").in_(AGENT_RUN_ACTIVE_STATUSES),
        ),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    access_source: Mapped[str] = mapped_column(String(20), nullable=False)
    consumer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    worker_generation: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    worker_task_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    checkpoint_phase: Mapped[str] = mapped_column(
        String(20), nullable=False, default="agent", server_default="agent"
    )
    grounding_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_started", server_default="not_started"
    )
    grounding_meta: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    plan: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_summary: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    model_usage: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AgentRunSnapshot(Base):
    __tablename__ = "agent_run_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "run_id", "agent_id"],
            ["agent_runs.workspace_id", "agent_runs.id", "agent_runs.agent_id"],
            name="fk_agent_run_snapshots_run_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "agent_id", "agent_publication_version_id"],
            [
                "agent_publication_versions.workspace_id",
                "agent_publication_versions.agent_id",
                "agent_publication_versions.id",
            ],
            name="fk_agent_run_snapshots_publication_workspace",
        ),
        CheckConstraint(
            "knowledge_query_mode IN ('required', 'agentic')",
            name="ck_agent_run_snapshots_knowledge_query_mode",
        ),
        CheckConstraint(
            "configuration_source IN ('draft', 'published', 'legacy')",
            name="ck_agent_run_snapshots_configuration_source",
        ),
        CheckConstraint(
            "snapshot_schema_version >= 1",
            name="ck_agent_run_snapshots_schema_version",
        ),
        CheckConstraint(
            "(configuration_source = 'published' AND agent_publication_version_id IS NOT NULL) "
            "OR (configuration_source IN ('draft', 'legacy') "
            "AND agent_publication_version_id IS NULL)",
            name="ck_agent_run_snapshots_publication_source",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    snapshot_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_source: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_publication_version_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_base_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    knowledge_query_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    mcp_tools: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    application_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    application_snapshot_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    tool_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    model_id: Mapped[str] = mapped_column(String(36), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_agent_run_events_run_workspace",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
