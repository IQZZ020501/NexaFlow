from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.time import AppDateTime

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
    expires_at: AppDateTime | None = None

    _trim_title = field_validator("title")(_trim_required)
    _trim_body = field_validator("body")(_trim_required)


class AnnouncementUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=100_000)
    severity: AnnouncementSeverity | None = None
    pinned: bool | None = None
    expires_at: AppDateTime | None = None

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
    published_at: AppDateTime | None
    expires_at: AppDateTime | None
    created_by_user_id: str | None
    updated_by_user_id: str | None
    created_at: AppDateTime
    updated_at: AppDateTime


class AnnouncementMessageResponse(BaseModel):
    id: str
    kind: Literal["announcement"] = "announcement"
    scope_type: Literal["global", "workspace"]
    workspace_id: str | None
    title: str
    body: str
    severity: AnnouncementSeverity
    pinned: bool
    published_at: AppDateTime
    expires_at: AppDateTime | None
    is_read: bool
    read_at: AppDateTime | None
    created_at: AppDateTime


class MessageUnreadCountResponse(BaseModel):
    count: Annotated[int, Field(ge=0)]
    next_expiration_at: AppDateTime | None
