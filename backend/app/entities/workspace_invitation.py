from dataclasses import dataclass, field
from datetime import datetime

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class WorkspaceInvitation:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    username: str | None = None
    email: str | None = None
    name: str | None = None
    role: str = "member"
    token_hash: str = ""
    invited_by_user_id: str = ""
    expires_at: datetime = field(default_factory=utc_now)
    accepted_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
