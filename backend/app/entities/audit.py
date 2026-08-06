from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class AuditLog:
    id: str = field(default_factory=new_id)
    actor_user_id: str = ""
    actor_username: str = ""
    actor_name: str = ""
    workspace_id: str | None = None
    action: str = ""
    resource_type: str = ""
    resource_id: str = ""
    resource_name: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
