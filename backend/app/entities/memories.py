"""User-owned, application-scoped long-term memory values."""

from dataclasses import dataclass, field
from datetime import datetime

from app.entities.defaults import new_id, utc_now


@dataclass
class MemoryPreferences:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    user_id: str = ""
    enabled: bool = True
    automatic: bool = True
    epoch: int = 0
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class UserMemory:
    id: str = field(default_factory=new_id)
    profile_id: str = ""
    project_id: str = ""
    category: str = "preference"
    key: str = ""
    content: str = ""
    origin: str = "manual"
    source_run_id: str | None = None
    source_quote: str = ""
    source_created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class MemoryJob:
    id: str = field(default_factory=new_id)
    profile_id: str = ""
    run_id: str = ""
    epoch: int = 0
    status: str = "pending"
    attempts: int = 0
    available_at: datetime = field(default_factory=utc_now)
    lease_token: str | None = None
