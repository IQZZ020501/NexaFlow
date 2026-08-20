from dataclasses import dataclass, field
from datetime import datetime

from app.infrastructure.model_utils import utc_now


SMTP_SETTINGS_ID = "default"


@dataclass
class SmtpSettings:
    """Global SMTP configuration stored as a singleton row."""

    id: str = SMTP_SETTINGS_ID
    host: str = ""
    port: int = 587
    username: str = ""
    password_ciphertext: str | None = None
    password_hint: str | None = None
    security: str = "starttls"
    from_email: str = ""
    from_name: str = ""
    site_url: str = ""
    enabled: bool = False
    timeout_seconds: float = 10.0
    updated_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
