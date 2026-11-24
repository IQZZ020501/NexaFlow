"""SQLAlchemy ORM model for per-user task notifications."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.defaults import new_id, utc_now
from app.infra.db.base import Base


class UserNotification(Base):
    """Per-user deduplicated notification persisted from automation execution runs."""

    __tablename__ = "user_notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "dedup_key",
            name="uq_user_notifications_dedup",
        ),
        CheckConstraint(
            "event_type IN "
            "('succeeded', 'failed', 'cancelled', 'awaiting_approval', 'awaiting_input')",
            name="ck_user_notifications_event_type",
        ),
        Index(
            "ix_user_notifications_user_inbox",
            "user_id",
            "workspace_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_user_notifications_unread",
            "user_id",
            "read_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    automation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("automations.id", ondelete="SET NULL"),
        nullable=True,
    )
    execution_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("automation_executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(255))
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
