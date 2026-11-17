from dataclasses import dataclass, field
from datetime import datetime

from app.entities.defaults import new_id, utc_now


@dataclass
class McpRemoteTask:
    id: str = field(default_factory=new_id)
    invocation_id: str = ""
    workspace_id: str = ""
    server_id: str = ""
    server_binding: str = ""
    request_key: str = ""
    contract: dict = field(default_factory=dict)
    remote_id: str | None = None
    status: str = "submitting"
    cancel_requested: bool = False
    cancel_owner: str | None = None
    cancel_lease_until: datetime | None = None
    next_cancel_at: datetime = field(default_factory=utc_now)
    cancel_attempts: int = 0
    deadline_at: datetime = field(default_factory=utc_now)
    last_error: str | None = None
    updated_at: datetime = field(default_factory=utc_now)
