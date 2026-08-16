"""Public HTTP schemas for the unified Tool catalog."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


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


class ToolDetailResponse(ToolSummaryResponse):
    version_id: str
    revision: int
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    approval: Literal["auto", "each_call", "disabled"]
    effect: Literal["pure", "external_read", "external_write", "unknown"]
    workflow_callable: bool
    parallel_safe: bool


__all__ = [
    "ToolDetailResponse",
    "ToolRefSchema",
    "ToolSourceSummaryResponse",
    "ToolSummaryResponse",
]
