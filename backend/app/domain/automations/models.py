"""SQLAlchemy ORM models for automations and execution triggers."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.entities.defaults import new_id, utc_now
from app.infra.db.base import Base

AUTOMATION_STATUS_ACTIVE = "active"
AUTOMATION_STATUS_PAUSED = "paused"
AUTOMATION_STATUS_COMPLETED = "completed"

EXECUTION_DISPATCH_QUEUED = "queued"
EXECUTION_DISPATCH_PENDING = "pending_dispatch"
EXECUTION_DISPATCH_DISPATCHED = "dispatched"
EXECUTION_DISPATCH_SKIPPED = "skipped"
EXECUTION_DISPATCH_REJECTED = "rejected"


class Automation(Base):
    """Scheduled or webhook automation targeting a published Agent or Workflow."""

    __tablename__ = "automations"
    __table_args__ = (
        CheckConstraint(
            "target_app_type IN ('agent', 'workflow')",
            name="ck_automations_target_app_type",
        ),
        CheckConstraint(
            "trigger_type IN ('once', 'daily', 'weekly', 'webhook')",
            name="ck_automations_trigger_type",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'completed')",
            name="ck_automations_status",
        ),
        CheckConstraint(
            "approval_mode IN ('always_ask', 'ask_risky', 'full_access')",
            name="ck_automations_approval_mode",
        ),
        Index(
            "ix_automations_due",
            "status",
            "next_run_at",
        ),
        Index(
            "ix_automations_workspace_owner",
            "workspace_id",
            "owner_user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    owner_user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    target_app_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        index=True,
    )
    target_app_type: Mapped[str] = mapped_column(String(20))
    publication_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_publication_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    workflow_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("workflow_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_version_number: Mapped[int] = mapped_column(Integer)
    approval_mode: Mapped[str] = mapped_column(String(24), default="always_ask")
    trigger_type: Mapped[str] = mapped_column(String(20))
    trigger_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notification_config: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    webhook_hook_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    webhook_secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    webhook_secret_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default=AUTOMATION_STATUS_ACTIVE)
    config_revision: Mapped[int] = mapped_column(Integer, default=1)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    missed_run_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AutomationExecution(Base):
    """Trigger receipt and dispatch record linked to at most one root AgentRun."""

    __tablename__ = "automation_executions"
    __table_args__ = (
        UniqueConstraint(
            "automation_id",
            "dedup_key",
            name="uq_automation_executions_dedup",
        ),
        UniqueConstraint(
            "run_id",
            name="uq_automation_executions_run_id",
        ),
        CheckConstraint(
            "trigger_source IN ('schedule', 'webhook', 'manual')",
            name="ck_automation_executions_trigger_source",
        ),
        CheckConstraint(
            "dispatch_status IN "
            "('queued', 'pending_dispatch', 'dispatched', 'skipped', 'rejected')",
            name="ck_automation_executions_dispatch_status",
        ),
        Index(
            "ix_automation_executions_lookup",
            "automation_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_automation_executions_pending_dispatch",
            "dispatch_status",
            "created_at",
        ),
        Index(
            "ix_automation_executions_unclosed_notifications",
            "notification_closed",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    automation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("automations.id", ondelete="CASCADE"),
        index=True,
    )
    owner_user_id: Mapped[str] = mapped_column(String(36), index=True)
    trigger_source: Mapped[str] = mapped_column(String(20))
    dedup_key: Mapped[str] = mapped_column(String(255))
    config_revision: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frozen_input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    frozen_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dispatch_status: Mapped[str] = mapped_column(
        String(24), default=EXECUTION_DISPATCH_QUEUED
    )
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    missed_count_before: Mapped[int] = mapped_column(Integer, default=0)
    last_reconciled_run_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
