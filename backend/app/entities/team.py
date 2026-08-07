from dataclasses import dataclass, field
from datetime import datetime

from app.infrastructure.model_utils import new_id, utc_now

TEAM_MEMBER_ROLES = {"admin", "member"}


@dataclass
class Team:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    name: str = ""
    description: str = ""
    slug: str = ""
    status: str = "active"
    is_default: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class TeamMembership:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    team_id: str = ""
    user_id: str = ""
    role: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
