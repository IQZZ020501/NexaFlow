from typing import Any

from pydantic import BaseModel, Field

from app.schemas.time import AppDateTime


class SystemLogResponse(BaseModel):
    id: str
    level: str
    event: str
    message: str
    path: str | None
    method: str | None
    status_code: int | None
    user_id: str | None
    username: str | None
    ip_address: str | None
    details: dict[str, Any] = Field(default_factory=dict)
    stack_trace: str | None = None
    created_at: AppDateTime
