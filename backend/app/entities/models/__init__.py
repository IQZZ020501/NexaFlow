from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.entities.defaults import new_id, utc_now


@dataclass(kw_only=True)
class RegisteredModel:
    workspace_id: str
    name: str
    provider: str
    model_type: str
    model_name: str
    created_by_user_id: str
    id: str = field(default_factory=new_id)
    visibility: str = "workspace"
    folder_id: str | None = None
    provider_type: str = "openai_compatible"
    api_base: str = ""
    api_key_ciphertext: str | None = None
    api_key_hint: str | None = None
    api_key_updated_at: datetime | None = None
    credential_config: dict[str, Any] = field(default_factory=dict)
    credential_secret_hints: dict[str, str] = field(default_factory=dict)
    status: str = "active"
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
