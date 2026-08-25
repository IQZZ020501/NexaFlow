from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now


class ToolSource(Base):
    __tablename__ = "tool_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "mcp_server_id"],
            ["mcp_servers.workspace_id", "mcp_servers.id"],
            name="fk_tool_sources_mcp_server_workspace",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_tool_sources_workspace_id"
        ),
        UniqueConstraint(
            "workspace_id", "mcp_server_id", name="uq_tool_sources_mcp_server"
        ),
        UniqueConstraint(
            "workspace_id",
            "kind",
            "name",
            name="uq_tool_sources_workspace_kind_name",
        ),
        CheckConstraint(
            "kind IN ('builtin', 'python', 'mcp')",
            name="ck_tool_sources_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'archived')",
            name="ck_tool_sources_status",
        ),
        CheckConstraint(
            "(kind = 'mcp' AND ((mcp_server_id IS NOT NULL "
            "AND status IN ('active', 'disabled')) OR "
            "(mcp_server_id IS NULL AND status = 'archived'))) OR "
            "(kind IN ('builtin', 'python') AND mcp_server_id IS NULL)",
            name="ck_tool_sources_mcp_server_kind",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mcp_server_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "folder_id"],
            ["resource_folders.workspace_id", "resource_folders.id"],
            name="fk_tools_folder_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["tool_sources.workspace_id", "tool_sources.id"],
            name="fk_tools_source_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "id", "current_version_id"],
            [
                "tool_versions.workspace_id",
                "tool_versions.tool_id",
                "tool_versions.id",
            ],
            name="fk_tools_current_version_workspace",
            use_alter=True,
        ),
        UniqueConstraint("workspace_id", "id", name="uq_tools_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "function_name",
            name="uq_tools_workspace_function_name",
        ),
        UniqueConstraint(
            "source_id", "stable_key", name="uq_tools_source_stable_key"
        ),
        CheckConstraint(
            "kind IN ('builtin', 'python', 'mcp')",
            name="ck_tools_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'archived')",
            name="ck_tools_status",
        ),
        CheckConstraint(
            "availability IN ('available', 'unavailable')",
            name="ck_tools_availability",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    folder_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(255), nullable=False)
    function_name: Mapped[str] = mapped_column(String(255), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    availability: Mapped[str] = mapped_column(
        String(20), nullable=False, default="available", server_default="available"
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ToolDraft(Base):
    __tablename__ = "tool_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tool_id"],
            ["tools.workspace_id", "tools.id"],
            name="fk_tool_drafts_tool_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_tool_drafts_workspace_id"
        ),
        UniqueConstraint(
            "workspace_id", "tool_id", name="uq_tool_drafts_tool"
        ),
        CheckConstraint("revision >= 1", name="ck_tool_drafts_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    execution_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ToolVersion(Base):
    __tablename__ = "tool_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tool_id"],
            ["tools.workspace_id", "tools.id"],
            name="fk_tool_versions_tool_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_tool_versions_workspace_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "tool_id",
            "id",
            name="uq_tool_versions_workspace_tool_id",
        ),
        UniqueConstraint(
            "tool_id", "revision", name="uq_tool_versions_tool_revision"
        ),
        UniqueConstraint(
            "tool_id",
            "definition_hash",
            name="uq_tool_versions_tool_definition_hash",
        ),
        CheckConstraint("revision >= 1", name="ck_tool_versions_revision"),
        CheckConstraint(
            "length(definition_hash) = 64",
            name="ck_tool_versions_definition_hash",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    execution_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ToolPolicy(Base):
    __tablename__ = "tool_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tool_id", "tool_version_id"],
            [
                "tool_versions.workspace_id",
                "tool_versions.tool_id",
                "tool_versions.id",
            ],
            name="fk_tool_policies_version_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_tool_policies_workspace_id"
        ),
        UniqueConstraint(
            "workspace_id", "tool_id", name="uq_tool_policies_tool"
        ),
        CheckConstraint("revision >= 1", name="ck_tool_policies_revision"),
        CheckConstraint(
            "length(definition_hash) = 64",
            name="ck_tool_policies_definition_hash",
        ),
        CheckConstraint(
            "approval IN ('auto', 'each_call', 'disabled')",
            name="ck_tool_policies_approval",
        ),
        CheckConstraint(
            "effect IN ('pure', 'external_read', 'external_write', 'unknown')",
            name="ck_tool_policies_effect",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tool_version_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approval: Mapped[str] = mapped_column(String(20), nullable=False)
    effect: Mapped[str] = mapped_column(String(30), nullable=False)
    allowed_access_sources: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    workflow_callable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    parallel_safe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ApplicationToolBinding(Base):
    __tablename__ = "application_tool_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "application_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_application_tool_bindings_application_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "tool_id", "tool_version_id"],
            [
                "tool_versions.workspace_id",
                "tool_versions.tool_id",
                "tool_versions.id",
            ],
            name="fk_application_tool_bindings_version_workspace",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_application_tool_bindings_workspace_id",
        ),
        UniqueConstraint(
            "application_id",
            "tool_id",
            name="uq_application_tool_bindings_application_tool",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tool_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tool_version_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    bound_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "root_run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_tool_invocations_root_run_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_tool_invocations_run_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "tool_id", "tool_version_id"],
            [
                "tool_versions.workspace_id",
                "tool_versions.tool_id",
                "tool_versions.id",
            ],
            name="fk_tool_invocations_version_workspace",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_tool_invocations_workspace_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_tool_invocations_idempotency",
        ),
        UniqueConstraint(
            "workspace_id",
            "origin",
            "run_id",
            "invocation_id",
            name="uq_tool_invocations_origin_run_invocation",
        ),
        CheckConstraint(
            "origin IN ('test', 'agent', 'workflow')",
            name="ck_tool_invocations_origin",
        ),
        CheckConstraint(
            "(origin = 'test' AND root_run_id IS NULL AND run_id IS NULL) OR "
            "(origin IN ('agent', 'workflow') AND root_run_id IS NOT NULL "
            "AND run_id IS NOT NULL)",
            name="ck_tool_invocations_origin_runs",
        ),
        CheckConstraint(
            "access_source IN ('console', 'public', 'api')",
            name="ck_tool_invocations_access_source",
        ),
        CheckConstraint(
            "status IN ('queued', 'awaiting_approval', 'approved', 'running', "
            "'succeeded', 'failed', 'rejected', 'uncertain', 'cancelled')",
            name="ck_tool_invocations_status",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('confirmed', 'uncertain')",
            name="ck_tool_invocations_outcome",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="ck_tool_invocations_attempts",
        ),
        CheckConstraint(
            "length(arguments_hash) = 64",
            name="ck_tool_invocations_arguments_hash",
        ),
        CheckConstraint(
            "(tool_id IS NULL AND tool_version_id IS NULL) OR "
            "(tool_id IS NOT NULL AND tool_version_id IS NOT NULL)",
            name="ck_tool_invocations_tool_version_pair",
        ),
        CheckConstraint(
            "(approved_by_user_id IS NULL AND approved_at IS NULL) OR "
            "(approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_tool_invocations_approval",
        ),
        CheckConstraint(
            "lease_expires_at IS NULL OR worker_task_id IS NOT NULL",
            name="ck_tool_invocations_lease",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    origin: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    root_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    invocation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    execution_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    access_source: Mapped[str] = mapped_column(String(20), nullable=False)
    tool_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tool_version_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    approved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_task_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    result_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class McpServer(Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_mcp_servers_workspace_name"),
        UniqueConstraint("workspace_id", "id", name="uq_mcp_servers_workspace_id"),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_mcp_servers_status",
        ),
        CheckConstraint(
            "transport IN ('streamable_http', 'sse', 'stdio')",
            name="ck_mcp_servers_transport",
        ),
        CheckConstraint(
            "network_policy IN ('public_only', 'deployment')",
            name="ck_mcp_servers_network_policy",
        ),
        CheckConstraint(
            "(transport IN ('streamable_http', 'sse') AND url IS NOT NULL "
            "AND stdio_command IS NULL AND stdio_config_ciphertext IS NULL) OR "
            "(transport = 'stdio' AND url IS NULL "
            "AND bearer_token_ciphertext IS NULL AND bearer_token_hint IS NULL AND "
            "((stdio_command IS NOT NULL AND stdio_config_ciphertext IS NOT NULL) OR "
            "(status = 'disabled' AND stdio_command IS NULL "
            "AND stdio_config_ciphertext IS NULL)))",
            name="ck_mcp_servers_transport_configuration",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    transport: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="streamable_http",
        server_default="streamable_http",
    )
    network_policy: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="public_only",
        server_default="public_only",
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    stdio_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    stdio_config_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    bearer_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    bearer_token_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class McpToolPolicy(Base):
    __tablename__ = "mcp_tool_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "mcp_server_id"],
            ["mcp_servers.workspace_id", "mcp_servers.id"],
            name="fk_mcp_tool_policies_server_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id",
            "mcp_server_id",
            "tool_name",
            name="uq_mcp_tool_policies_tool",
        ),
        CheckConstraint(
            "mode IN ('approval_required', 'read_only', 'disabled')",
            name="ck_mcp_tool_policies_mode",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    mcp_server_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False, default="approval_required")
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
