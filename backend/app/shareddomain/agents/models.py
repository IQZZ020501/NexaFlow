from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    JSON,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_agents_workspace_name"),
        UniqueConstraint("workspace_id", "id", name="uq_agents_workspace_id"),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_agents_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(ForeignKey("model.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


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


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_runs_agent_workspace",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('planning', 'planned', 'running', 'awaiting_approval', 'succeeded', 'failed')",
            name="ck_agent_runs_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requested_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_base_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    mcp_tools: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)
    model_id: Mapped[str] = mapped_column(String(36), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planning", index=True)
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    plan_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    pending_approval: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resumable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
