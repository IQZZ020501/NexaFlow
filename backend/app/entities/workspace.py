from dataclasses import dataclass, field
from datetime import datetime

from app.infrastructure.model_utils import new_id, utc_now

WORKSPACE_MEMBER_ROLES = {"admin", "member"}
WORKSPACE_ADMIN_ROLE = "admin"


@dataclass
class Workspace:
    id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    slug: str = ""
    status: str = "active"
    is_default: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class WorkspaceMembership:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    user_id: str = ""
    role: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
