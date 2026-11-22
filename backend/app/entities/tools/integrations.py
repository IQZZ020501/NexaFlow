from dataclasses import dataclass, field
from datetime import datetime

from app.entities.defaults import new_id, utc_now


@dataclass
class IntegrationConnection:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    user_id: str = ""
    provider: str = ""
    source_id: str | None = None
    status: str = "disconnected"
    generation: int = 0
    application_revision: int = 0
    secrets_ciphertext: str = ""
    access_expires_at: datetime | None = None
    refreshable: bool = False
    refresh_owner: str | None = None
    refresh_expires_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class IntegrationAuthorization:
    id: str = field(default_factory=new_id)
    connection_id: str = ""
    state_hash: str = ""
    generation: int = 0
    status: str = "pending"
    secrets_ciphertext: str = ""
    redirect_uri: str = ""
    expires_at: datetime = field(default_factory=utc_now)
    next_poll_at: datetime = field(default_factory=utc_now)
