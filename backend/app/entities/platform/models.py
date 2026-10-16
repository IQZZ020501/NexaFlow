from dataclasses import dataclass, field
from datetime import datetime

from app.entities.defaults import utc_now


@dataclass
class PlatformSecret:
    """One deployment-wide secret key, created once and never rewritten."""

    name: str = ""
    value: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
