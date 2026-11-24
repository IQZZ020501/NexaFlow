"""Domain entity dataclasses for user task notifications."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.entities.defaults import new_id, utc_now

USER_NOTIFICATION_EVENT_TYPES = (
    "succeeded",
    "failed",
    "cancelled",
    "awaiting_approval",
    "awaiting_input",
)


@dataclass(slots=True)
class UserNotification:
    """Persistent, per-user deduplicated inbox notification for an execution event."""

    user_id: str
    workspace_id: str
    event_type: str
    title: str
    dedup_key: str
    id: str = field(default_factory=new_id)
    automation_id: str | None = None
    execution_id: str | None = None
    run_id: str | None = None
    body: str = ""
    metadata_json: dict[str, Any] = field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
