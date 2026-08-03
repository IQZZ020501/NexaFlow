from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class McpToolResponse(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class McpServerResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    url: str
    tools: list[McpToolResponse]
    status: str
    has_bearer_token: bool
    bearer_token_hint: str | None
    last_error: str | None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class McpServerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2000)
    bearer_token: str | None = Field(default=None, max_length=8000)
