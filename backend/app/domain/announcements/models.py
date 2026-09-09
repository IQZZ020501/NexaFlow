from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.defaults import new_id, utc_now
from app.infra.db.base import Base


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('global', 'workspace')",
            name="ck_announcements_scope_type",
        ),
        CheckConstraint(
            "(scope_type = 'global' AND workspace_id IS NULL) OR "
            "(scope_type = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_announcements_scope_workspace",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="ck_announcements_severity",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_announcements_status",
        ),
        CheckConstraint(
            "expires_at IS NULL OR published_at IS NULL OR expires_at > published_at",
            name="ck_announcements_expiry_after_publish",
        ),
        Index(
            "ix_announcements_visible",
            "scope_type",
            "workspace_id",
            "status",
            "published_at",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AnnouncementRead(Base):
    __tablename__ = "announcement_reads"
    __table_args__ = (
        PrimaryKeyConstraint("announcement_id", "user_id", name="pk_announcement_reads"),
        Index("ix_announcement_reads_user", "user_id", "read_at"),
    )

    announcement_id: Mapped[str] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
