from dataclasses import dataclass, field
from datetime import datetime

from app.entities.defaults import APP_TIMEZONE_NAME, new_id, utc_now


@dataclass
class WorkspaceGovernance:
    workspace_id: str = ""
    daily_run_limit: int | None = None
    monthly_token_limit: int | None = None
    alert_threshold_percent: int = 80
    retention_days: int | None = None
    timezone: str = APP_TIMEZONE_NAME
    updated_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class WorkspaceTokenMonth:
    workspace_id: str = ""
    period: str = ""
    used_tokens: int = 0
    reserved_tokens: int = 0


@dataclass
class ModelUsageReservation:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    period: str = ""
    model_id: str = ""
    state: str = "dispatched"
    reserved_tokens: int = 0
    charged_tokens: int = 0
    created_at: datetime = field(default_factory=utc_now)
