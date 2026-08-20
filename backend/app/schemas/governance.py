from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class WorkspaceGovernanceResponse(BaseModel):
    workspace_id: str
    daily_run_limit: int | None
    monthly_token_limit: int | None
    alert_threshold_percent: int
    retention_days: int | None
    timezone: str
    updated_at: datetime


class WorkspaceGovernanceUpdateRequest(BaseModel):
    daily_run_limit: int | None = Field(default=None, ge=1, le=10_000_000)
    monthly_token_limit: int | None = Field(default=None, ge=1, le=10_000_000_000)
    alert_threshold_percent: int = Field(default=80, ge=1, le=100)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def normalize_timezone(cls, value: str) -> str:
        """Normalize a timezone value by removing surrounding whitespace and defaulting blank values to `"UTC"`.
        
        Parameters:
            value (str): The timezone value to normalize.
        
        Returns:
            str: The trimmed timezone value, or `"UTC"` when the value is blank.
        """
        return value.strip() or "UTC"


class WorkspaceInventoryResponse(BaseModel):
    workspace_id: str
    members_total: int
    members_active: int
    teams_total: int
    teams_active: int
    agents_total: int
    knowledge_bases_total: int
    models_total: int
    tools_total: int
    workflows_total: int
    active_runs: int
    failed_runs_24h: int
    failed_tasks_24h: int
    updated_at: datetime


class HealthComponent(BaseModel):
    status: str
    detail: str | None = None


class AdminHealthResponse(BaseModel):
    status: str
    components: dict[str, HealthComponent]
    pending_tasks: int
    failed_logs_24h: int
    checked_at: datetime
