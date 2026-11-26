from typing import Any

from pydantic import BaseModel, Field

from app.schemas.time import AppDateTime


class AuditLogResponse(BaseModel):
    id: str
    actor_user_id: str
    actor_username: str
    actor_name: str
    workspace_id: str | None
    action: str
    resource_type: str
    resource_id: str
    resource_name: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: AppDateTime


class AuditRetentionPolicyResponse(BaseModel):
    retention_days: int | None = None
    updated_at: AppDateTime | None = None


class AuditRetentionPolicyUpdateRequest(BaseModel):
    retention_days: int | None = Field(default=None, ge=1, le=3650)
