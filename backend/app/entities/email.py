from dataclasses import dataclass, field
from datetime import datetime

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class EmailDelivery:
    id: str = field(default_factory=new_id)
    kind: str = ""
    payload_ciphertext: str = ""
    user_id: str | None = None
    source_type: str = ""
    source_id: str = ""
    status: str = "pending"
    attempts: int = 0
    max_attempts: int = 24
    next_attempt_at: datetime = field(default_factory=utc_now)
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    expires_at: datetime = field(default_factory=utc_now)
    last_error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class PasswordResetToken:
    id: str = field(default_factory=new_id)
    user_id: str = ""
    token_hash: str = ""
    expires_at: datetime = field(default_factory=utc_now)
    used_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
