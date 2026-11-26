from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.defaults import new_id, utc_now
from app.infra.db.base import Base

AUDIT_RETENTION_SETTINGS_ID = "default"
MIN_AUDIT_RETENTION_DAYS = 1
MAX_AUDIT_RETENTION_DAYS = 3650


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index(
            "ix_audit_logs_workspace_created_id",
            "workspace_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_audit_logs_created_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_username: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(120), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    resource_name: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditRetentionSettings(Base):
    """Global audit log retention configuration, limited to one ``default`` row."""

    __tablename__ = "audit_retention_settings"
    __table_args__ = (
        CheckConstraint("id = 'default'", name="ck_audit_retention_settings_singleton"),
        CheckConstraint(
            "retention_days IS NULL OR (retention_days >= 1 AND retention_days <= 3650)",
            name="ck_audit_retention_settings_days",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=AUDIT_RETENTION_SETTINGS_ID,
        server_default=AUDIT_RETENTION_SETTINGS_ID,
    )
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Opaque former actor id without a users FK so permanent user deletion keeps settings history.
    updated_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
