from dataclasses import dataclass, field
from datetime import datetime

from app.entities.defaults import new_id, utc_now


ANNOUNCEMENT_SCOPES = {"global", "workspace"}
ANNOUNCEMENT_SEVERITIES = {"info", "warning", "critical"}
ANNOUNCEMENT_STATUSES = {"draft", "published", "archived"}


@dataclass
class Announcement:
    id: str = field(default_factory=new_id)
    scope_type: str = "global"
    workspace_id: str | None = None
    title: str = ""
    body: str = ""
    severity: str = "info"
    pinned: bool = False
    status: str = "draft"
    published_at: datetime | None = None
    expires_at: datetime | None = None
    created_by_user_id: str | None = None
    updated_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class AnnouncementRead:
    announcement_id: str = ""
    user_id: str = ""
    read_at: datetime = field(default_factory=utc_now)
    dismissed_at: datetime | None = None
