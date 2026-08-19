from dataclasses import dataclass, field
from datetime import datetime

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class User:
    id: str = field(default_factory=new_id)
    username: str = ""
    email: str = ""
    name: str = ""
    password_hash: str = ""
    is_global_admin: bool = False
    must_change_password: bool = True
    is_active: bool = True
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class RefreshSession:
    id: str = field(default_factory=new_id)
    user_id: str = ""
    token_hash: str = ""
    expires_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    user_agent: str | None = None
    ip_address: str | None = None
    last_used_at: datetime = field(default_factory=utc_now)
    revoked_at: datetime | None = None
