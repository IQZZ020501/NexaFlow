from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now


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
