from dataclasses import dataclass, field
from datetime import datetime

from app.infrastructure.model_utils import APP_TIMEZONE_NAME, utc_now


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
