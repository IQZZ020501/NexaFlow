from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AnnouncementSeverity = Literal["info", "warning", "critical"]


def _trim_required(value: str | None) -> str:
    if value is None:
        raise ValueError("Value must not be null.")
    value = value.strip()
    if not value:
        raise ValueError("Value must not be empty.")
    return value


class AnnouncementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=100_000)
    severity: AnnouncementSeverity = "info"
    pinned: bool = False
    expires_at: datetime | None = None

    _trim_title = field_validator("title")(_trim_required)
    _trim_body = field_validator("body")(_trim_required)


class AnnouncementUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=100_000)
    severity: AnnouncementSeverity | None = None
    pinned: bool | None = None
    expires_at: datetime | None = None

    _trim_title = field_validator("title")(_trim_required)
    _trim_body = field_validator("body")(_trim_required)


class AnnouncementResponse(BaseModel):
    id: str
    scope_type: Literal["global", "workspace"]
    workspace_id: str | None
    title: str
    body: str
    severity: AnnouncementSeverity
    pinned: bool
    status: Literal["draft", "published", "archived"]
    published_at: datetime | None
    expires_at: datetime | None
    created_by_user_id: str | None
    updated_by_user_id: str | None
    created_at: datetime
    updated_at: datetime


class AnnouncementMessageResponse(BaseModel):
    id: str
    kind: Literal["announcement"] = "announcement"
    scope_type: Literal["global", "workspace"]
    workspace_id: str | None
    title: str
    body: str
    severity: AnnouncementSeverity
    pinned: bool
    published_at: datetime
    expires_at: datetime | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class MessageUnreadCountResponse(BaseModel):
    count: Annotated[int, Field(ge=0)]
