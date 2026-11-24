"""Contracts for personal task notifications returned by the message center."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.schemas.announcements.contracts import AnnouncementMessageResponse
from app.schemas.time import AppDateTime

UserNotificationEventType = Literal[
    "succeeded",
    "failed",
    "cancelled",
    "awaiting_approval",
    "awaiting_input",
]


class UserTaskNotificationMessageResponse(BaseModel):
    id: str
    kind: Literal["notification"] = "notification"
    scope_type: Literal["personal"] = "personal"
    workspace_id: str
    event_type: UserNotificationEventType
    title: str
    body: str
    severity: Literal["info", "warning", "critical"] = "info"
    pinned: bool = False
    automation_id: str | None = None
    automation_name: str | None = None
    execution_id: str | None = None
    run_id: str | None = None
    target_app_id: str | None = None
    target_app_type: Literal["agent", "workflow"] | None = None
    trigger_source: Literal["schedule", "webhook", "manual"] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    published_at: AppDateTime
    expires_at: AppDateTime | None = None
    is_read: bool
    read_at: AppDateTime | None
    created_at: AppDateTime


MessageListItemResponse = Annotated[
    AnnouncementMessageResponse | UserTaskNotificationMessageResponse,
    Field(discriminator="kind"),
]
