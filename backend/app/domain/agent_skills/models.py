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

from app.entities.defaults import new_id, utc_now
from app.infra.db.base import Base


class AgentSkill(Base):
    __tablename__ = "agent_skills"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_agent_skills_workspace_name"),
        UniqueConstraint("workspace_id", "id", name="uq_agent_skills_workspace_id"),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_agent_skills_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    draft_definition: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    current_published_version_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    created_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AgentSkillVersion(Base):
    __tablename__ = "agent_skill_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "skill_id"],
            ["agent_skills.workspace_id", "agent_skills.id"],
            name="fk_agent_skill_versions_skill_workspace",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "skill_id", "version_number", name="uq_agent_skill_versions_skill_number"
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_agent_skill_versions_workspace_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "skill_id",
            "id",
            name="uq_agent_skill_versions_workspace_skill_id",
        ),
        CheckConstraint("version_number >= 1", name="ck_agent_skill_versions_number"),
        CheckConstraint("schema_version >= 1", name="ck_agent_skill_versions_schema"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    definition_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by_user_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AgentSkillBinding(Base):
    __tablename__ = "agent_skill_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_skill_bindings_agent_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "skill_id", "skill_version_id"],
            [
                "agent_skill_versions.workspace_id",
                "agent_skill_versions.skill_id",
                "agent_skill_versions.id",
            ],
            name="fk_agent_skill_bindings_version_workspace",
        ),
        UniqueConstraint(
            "agent_id", "skill_id", name="uq_agent_skill_bindings_agent_skill"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    skill_version_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    bound_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


__all__ = ["AgentSkill", "AgentSkillBinding", "AgentSkillVersion"]
