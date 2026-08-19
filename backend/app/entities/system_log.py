from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class SystemLog:
    id: str = field(default_factory=new_id)
    level: str = "info"
    event: str = ""
    message: str = ""
    path: str | None = None
    method: str | None = None
    status_code: int | None = None
    user_id: str | None = None
    username: str | None = None
    ip_address: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    stack_trace: str | None = None
    created_at: datetime = field(default_factory=utc_now)
