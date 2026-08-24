from dataclasses import dataclass, field
from datetime import datetime

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class GeneratedArtifact:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    run_id: str | None = None
    idempotency_key: str = ""
    format: str = "html"
    filename: str = ""
    media_type: str = "text/html; charset=utf-8"
    content: bytes = b""
    size_bytes: int = 0
    expires_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
