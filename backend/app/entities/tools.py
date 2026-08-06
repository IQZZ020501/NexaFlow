from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class McpServer:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    name: str = ""
    url: str = ""
    bearer_token_ciphertext: str | None = None
    bearer_token_hint: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    status: str = "active"
    last_error: str | None = None
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
