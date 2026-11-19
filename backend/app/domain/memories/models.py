"""Long-term memory is owned by the reader, never the publishing identity."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.defaults import new_id, utc_now
from app.infra.db.base import Base


class MemoryPreferences(Base):
    __tablename__ = "user_memory_preferences"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_user_memory_owner"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    automatic: Mapped[bool] = mapped_column(Boolean, default=False)
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class UserMemory(Base):
    __tablename__ = "user_memories"
    __table_args__ = (
        UniqueConstraint("profile_id", "project_id", "key", name="uq_user_memory_key"),
        CheckConstraint(
            "category IN ('preference', 'background', 'goal', 'project')",
            name="ck_user_memory_category",
        ),
        CheckConstraint(
            "origin IN ('manual', 'explicit', 'automatic')",
            name="ck_user_memory_origin",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("user_memory_preferences.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(String(36), default="")
    category: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(String(600))
    origin: Mapped[str] = mapped_column(String(20), default="manual")
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_quote: Mapped[str] = mapped_column(String(600), default="")
    source_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class MemoryJob(Base):
    __tablename__ = "user_memory_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'done')", name="ck_user_memory_job_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("user_memory_preferences.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), unique=True
    )
    epoch: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    lease_token: Mapped[str | None] = mapped_column(Text, nullable=True)
