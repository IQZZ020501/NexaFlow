from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class McpServer:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    name: str = ""
    transport: str = "streamable_http"
    url: str | None = None
    stdio_command: str | None = None
    stdio_config_ciphertext: str | None = None
    bearer_token_ciphertext: str | None = None
    bearer_token_hint: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    status: str = "active"
    last_error: str | None = None
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class McpToolPolicy:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    mcp_server_id: str = ""
    tool_name: str = ""
    definition_hash: str = ""
    mode: str = "approval_required"
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
