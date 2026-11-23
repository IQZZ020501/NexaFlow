"""Domain entity dataclasses for scheduled and webhook automations."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.entities.defaults import new_id, utc_now

AUTOMATION_TARGET_APP_TYPES = ("agent", "workflow")
AUTOMATION_TRIGGER_TYPES = ("once", "daily", "weekly", "webhook")
AUTOMATION_STATUSES = ("active", "paused", "completed")
AUTOMATION_APPROVAL_MODES = ("always_ask", "ask_risky", "full_access")
AUTOMATION_EXECUTION_TRIGGER_SOURCES = ("schedule", "webhook", "manual")
AUTOMATION_EXECUTION_DISPATCH_STATUSES = (
    "queued",
    "pending_dispatch",
    "dispatched",
    "skipped",
    "rejected",
)


def _default_notification_config() -> dict[str, bool]:
    return {
        "on_succeeded": True,
        "on_failed": True,
        "on_cancelled": True,
        "on_awaiting_approval": True,
        "on_awaiting_input": True,
    }


@dataclass(slots=True)
class Automation:
    """User-owned automation binding a published application to a trigger."""

    workspace_id: str
    owner_user_id: str
    name: str
    target_app_id: str
    target_app_type: str
    target_version_number: int
    trigger_type: str
    id: str = field(default_factory=new_id)
    description: str = ""
    publication_version_id: str | None = None
    workflow_version_id: str | None = None
    approval_mode: str = "always_ask"
    trigger_config: dict[str, Any] = field(default_factory=dict)
    input_config: dict[str, Any] = field(default_factory=dict)
    notification_config: dict[str, bool] = field(
        default_factory=_default_notification_config
    )
    webhook_hook_id: str | None = None
    webhook_secret_ciphertext: str | None = None
    webhook_secret_hint: str | None = None
    webhook_secret_updated_at: datetime | None = None
    status: str = "active"
    config_revision: int = 1
    next_run_at: datetime | None = None
    last_triggered_at: datetime | None = None
    missed_run_count: int = 0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class AutomationExecution:
    """Persistent record of one automation trigger and its linked root Run."""

    workspace_id: str
    automation_id: str
    owner_user_id: str
    trigger_source: str
    dedup_key: str
    config_revision: int
    id: str = field(default_factory=new_id)
    scheduled_at: datetime | None = None
    received_at: datetime = field(default_factory=utc_now)
    dispatched_at: datetime | None = None
    payload_hash: str | None = None
    frozen_input: dict[str, Any] = field(default_factory=dict)
    frozen_config: dict[str, Any] = field(default_factory=dict)
    dispatch_status: str = "queued"
    skip_reason: str | None = None
    run_id: str | None = None
    missed_count_before: int = 0
    last_reconciled_run_status: str | None = None
    notification_closed: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
