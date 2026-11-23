"""Request and response schemas for workspace automations."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.agents.contracts import (
    AgentApprovalMode,
    AgentRunResponse,
    AgentToolCallResponse,
)
from app.schemas.time import AppDateTime
from app.schemas.workflows.contracts import WorkflowRunResponse

AutomationTargetAppType = Literal["agent", "workflow"]
AutomationTriggerType = Literal["once", "daily", "weekly", "webhook"]
AutomationStatus = Literal["active", "paused", "completed"]
AutomationInputMode = Literal["text", "json"]
AutomationTriggerSource = Literal["schedule", "webhook", "manual"]
AutomationDispatchStatus = Literal[
    "queued",
    "pending_dispatch",
    "dispatched",
    "skipped",
    "rejected",
]


def _trim_required(value: str | None) -> str:
    if value is None:
        raise ValueError("Value must not be null.")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("Value must not be empty.")
    return trimmed


class AutomationInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: AutomationInputMode = "text"
    text: str = Field(default="", max_length=4000)
    json_payload: dict[str, Any] = Field(default_factory=dict)
    webhook_input_path: str | None = Field(default=None, max_length=200)
    webhook_prompt_template: str | None = Field(default=None, max_length=4000)


class AutomationNotificationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_succeeded: bool = True
    on_failed: bool = True
    on_cancelled: bool = True
    on_awaiting_approval: bool = True
    on_awaiting_input: bool = True


class AutomationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    target_app_id: str = Field(min_length=1, max_length=36)
    publication_version_id: str | None = Field(default=None, max_length=36)
    workflow_version_id: str | None = Field(default=None, max_length=36)
    approval_mode: AgentApprovalMode = "always_ask"
    trigger_type: AutomationTriggerType
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    input_config: AutomationInputConfig
    notification_config: AutomationNotificationPreferences = Field(
        default_factory=AutomationNotificationPreferences
    )

    _trim_name = field_validator("name")(_trim_required)


class AutomationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    publication_version_id: str | None = Field(default=None, max_length=36)
    workflow_version_id: str | None = Field(default=None, max_length=36)
    approval_mode: AgentApprovalMode | None = None
    trigger_type: AutomationTriggerType | None = None
    trigger_config: dict[str, Any] | None = None
    input_config: AutomationInputConfig | None = None
    notification_config: AutomationNotificationPreferences | None = None

    @field_validator("name")
    @classmethod
    def _validate_optional_name(cls, value: str | None) -> str | None:
        return None if value is None else _trim_required(value)


class AutomationExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class AutomationToolApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool


class AutomationArtifactLinkResponse(BaseModel):
    artifact_id: str
    format: str
    filename: str
    media_type: str
    download_url: str
    expires_at: AppDateTime
    size_bytes: int
    relative_path: str | None = None


class AutomationExecutionSummaryResponse(BaseModel):
    id: str
    automation_id: str
    workspace_id: str
    trigger_source: AutomationTriggerSource
    dedup_key: str
    config_revision: int
    scheduled_at: AppDateTime | None
    received_at: AppDateTime
    dispatched_at: AppDateTime | None
    dispatch_status: AutomationDispatchStatus
    skip_reason: str | None
    run_id: str | None
    run_status: str | None = None
    missed_count_before: int
    created_at: AppDateTime
    updated_at: AppDateTime


class AutomationExecutionDetailResponse(AutomationExecutionSummaryResponse):
    frozen_input: dict[str, Any] = Field(default_factory=dict)
    frozen_config: dict[str, Any] = Field(default_factory=dict)
    agent_run: AgentRunResponse | None = None
    workflow_run: WorkflowRunResponse | None = None
    tool_calls: list[AgentToolCallResponse] = Field(default_factory=list)
    artifacts: list[AutomationArtifactLinkResponse] = Field(default_factory=list)


class AutomationExecutionListResponse(BaseModel):
    items: list[AutomationExecutionSummaryResponse]
    total: int
    limit: int
    offset: int


class AutomationResponse(BaseModel):
    id: str
    workspace_id: str
    owner_user_id: str
    name: str
    description: str
    target_app_id: str
    target_app_name: str
    target_app_type: AutomationTargetAppType
    publication_version_id: str | None
    workflow_version_id: str | None
    target_version_number: int
    approval_mode: AgentApprovalMode
    trigger_type: AutomationTriggerType
    trigger_config: dict[str, Any]
    input_config: AutomationInputConfig
    notification_config: AutomationNotificationPreferences
    webhook_hook_id: str | None
    webhook_url: str | None
    webhook_secret_hint: str | None
    webhook_secret_updated_at: AppDateTime | None
    status: AutomationStatus
    config_revision: int
    next_run_at: AppDateTime | None
    last_triggered_at: AppDateTime | None
    missed_run_count: int
    latest_execution: AutomationExecutionSummaryResponse | None = None
    created_at: AppDateTime
    updated_at: AppDateTime


class AutomationCreateResponse(AutomationResponse):
    webhook_secret: str | None = None


class AutomationListResponse(BaseModel):
    items: list[AutomationResponse]
    total: int
    limit: int
    offset: int


class AutomationWebhookSecretRotateResponse(BaseModel):
    automation_id: str
    webhook_hook_id: str
    webhook_url: str
    webhook_secret: str
    webhook_secret_hint: str
    webhook_secret_updated_at: AppDateTime


class AutomationWebhookReceiptResponse(BaseModel):
    accepted: bool = True
    deduplicated: bool = False
    automation_id: str
    execution_id: str
    dispatch_status: AutomationDispatchStatus
    run_id: str | None = None
    received_at: AppDateTime
