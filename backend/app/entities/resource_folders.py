from dataclasses import dataclass, field
from datetime import datetime

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class ResourceFolder:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    resource_type: str = "knowledge"
    parent_id: str | None = None
    name: str = ""
    created_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
