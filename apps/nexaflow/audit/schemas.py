from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditLogResponse(BaseModel):
    id: str
    actor_user_id: str
    actor_username: str
    actor_name: str
    action: str
    resource_type: str
    resource_id: str
    resource_name: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
