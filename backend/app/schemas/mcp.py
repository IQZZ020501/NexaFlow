from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class McpToolResponse(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any] | None = None
    definition_hash: str = ""
    policy_mode: Literal["approval_required", "read_only", "disabled"] = "read_only"


class McpServerResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    transport: Literal["streamable_http", "sse", "stdio"]
    url: str | None
    stdio_command: str | None
    tools: list[McpToolResponse]
    status: str
    has_bearer_token: bool
    bearer_token_hint: str | None
    last_error: str | None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class McpStdioConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=1000)
    args: list[str] = Field(default_factory=list, max_length=64)
    cwd: str | None = Field(default=None, max_length=1000)
    env: dict[str, str] = Field(default_factory=dict, max_length=32)


class McpServerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    transport: Literal["streamable_http", "sse", "stdio"] = "streamable_http"
    url: str | None = Field(default=None, max_length=2000)
    stdio_config: McpStdioConfigRequest | None = None
    bearer_token: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def validate_transport_fields(self) -> "McpServerCreateRequest":
        if self.transport == "stdio":
            if (
                self.stdio_config is None
                or self.url is not None
                or self.bearer_token is not None
            ):
                raise ValueError("stdio requires only a stdio configuration.")
        elif not self.url or self.stdio_config is not None:
            raise ValueError(
                "HTTP MCP transports require a URL and no stdio configuration."
            )
        return self


class McpToolPolicyRequest(BaseModel):
    mode: Literal["approval_required", "read_only", "disabled"]


class McpToolPolicyResponse(BaseModel):
    workspace_id: str
    mcp_server_id: str
    tool_name: str
    definition_hash: str
    mode: Literal["approval_required", "read_only", "disabled"]
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
