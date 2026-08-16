"""Public HTTP schemas for the unified Tool catalog."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.user import UserResponse


ToolKind = Literal["builtin", "python", "mcp"]
_ToolId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=36),
]


class ToolRefSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: _ToolId
    version_id: _ToolId


class _PublicToolResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ToolSourceSummaryResponse(_PublicToolResponse):
    id: str
    name: str
    kind: ToolKind
    transport: Literal["streamable_http", "sse", "stdio"] | None = None


class ToolSummaryResponse(_PublicToolResponse):
    id: str
    workspace_id: str
    kind: ToolKind
    function_name: str
    display_name: str
    description: str
    current_version_id: str | None
    status: str
    availability: Literal["available", "unavailable"]
    source: ToolSourceSummaryResponse
    created_by_user_id: str | None
    permission: Literal["owner", "admin", "view", "use"] | None
    can_view: bool
    can_use: bool
    can_manage: bool


class ToolDraftResponse(_PublicToolResponse):
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    code: str
    revision: int
    updated_at: datetime


class ToolDetailResponse(ToolSummaryResponse):
    version_id: str | None
    revision: int | None
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    approval: Literal["auto", "each_call", "disabled"] | None
    effect: Literal["pure", "external_read", "external_write", "unknown"] | None
    workflow_callable: bool
    parallel_safe: bool
    draft: ToolDraftResponse | None = None


class PythonToolCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    code: str = Field(min_length=1, max_length=8192)


class PythonToolDraftUpdateRequest(PythonToolCreateRequest):
    expected_revision: int = Field(ge=1)


class ToolTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolInvocationResponse(_PublicToolResponse):
    id: str
    tool_id: str
    tool_version_id: str
    status: Literal[
        "queued",
        "awaiting_approval",
        "approved",
        "running",
        "succeeded",
        "failed",
        "rejected",
        "uncertain",
        "cancelled",
    ]
    attempts: int
    result_data: Any = None
    result_summary: str
    outcome: Literal["confirmed", "uncertain"] | None
    error_code: str | None
    error_message: str | None
    usage: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ToolPermissionUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission: Literal["view", "use"]


class ToolPermissionResponse(_PublicToolResponse):
    user: UserResponse
    permission: Literal["view", "use"]


__all__ = [
    "ToolDetailResponse",
    "ToolDraftResponse",
    "ToolInvocationResponse",
    "ToolPermissionResponse",
    "ToolPermissionUpsertRequest",
    "ToolRefSchema",
    "ToolSourceSummaryResponse",
    "ToolSummaryResponse",
    "ToolTestRequest",
    "PythonToolCreateRequest",
    "PythonToolDraftUpdateRequest",
]
