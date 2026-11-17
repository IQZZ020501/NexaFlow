from dataclasses import dataclass, field
from datetime import datetime

from app.entities.defaults import new_id, utc_now


@dataclass
class McpOAuthConnection:
    id: str = field(default_factory=new_id)
    server_id: str = ""
    configuration: dict = field(default_factory=dict)
    secrets_ciphertext: str = ""
    status: str = "disconnected"
    generation: int = 0
    access_expires_at: datetime | None = None
    refresh_owner: str | None = None
    refresh_expires_at: datetime | None = None
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class McpOAuthAttempt:
    id: str = field(default_factory=new_id)
    connection_id: str = ""
    actor_id: str = ""
    generation: int = 0
    state_hash: str = ""
    verifier_ciphertext: str = ""
    redirect_uri: str = ""
    status: str = "pending"
    expires_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class McpOAuthRevocation:
    id: str = field(default_factory=new_id)
    configuration: dict = field(default_factory=dict)
    secrets_ciphertext: str = ""
    attempts: int = 0
    next_attempt_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
