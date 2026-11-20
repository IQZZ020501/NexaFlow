"""Public HTTP schemas for the unified Tool catalog."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.identity.contracts import UserResponse

ToolKind = Literal["builtin", "mcp", "integration"]
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


class ToolSourceDetailResponse(ToolSourceSummaryResponse):
    mcp_server_id: str | None = None
    auth_mode: Literal["bearer", "oauth"] = "bearer"
    workspace_id: str
    status: str
    url: str | None
    stdio_command: str | None
    has_bearer_token: bool
    bearer_token_hint: str | None
    last_error: str | None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime
    tool_count: int


class ToolSummaryResponse(_PublicToolResponse):
    id: str
    workspace_id: str
    folder_id: str | None = None
    kind: ToolKind
    function_name: str
    display_name: str
    description: str
    current_version_id: str | None
    status: str
    availability: Literal["available", "unavailable"]
    policy_mode: Literal["approval_required", "read_only", "disabled"] | None = None
    allowed_access_sources: list[str] | None = None
    source: ToolSourceSummaryResponse
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime
    permission: Literal["owner", "admin", "view", "use"] | None
    can_view: bool
    can_use: bool
    can_manage: bool


class ToolDetailResponse(ToolSummaryResponse):
    version_id: str | None
    revision: int | None
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    approval: Literal["auto", "each_call", "disabled"] | None
    effect: Literal["pure", "external_read", "external_write", "unknown"] | None
    workflow_callable: bool
    parallel_safe: bool


class ToolPermissionUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission: Literal["view", "use"]


class ToolPolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["approval_required", "read_only", "disabled"]


class ToolPermissionResponse(_PublicToolResponse):
    user: UserResponse
    permission: Literal["view", "use"]


__all__ = [
    "ToolDetailResponse",
    "ToolPermissionResponse",
    "ToolPermissionUpsertRequest",
    "ToolPolicyUpdateRequest",
    "ToolRefSchema",
    "ToolSourceDetailResponse",
    "ToolSourceSummaryResponse",
    "ToolSummaryResponse",
]
