from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentMcpToolRef(BaseModel):
    server_id: str = Field(min_length=1, max_length=36)
    tool_name: str = Field(min_length=1, max_length=255)


class AgentResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    instructions: str
    model_id: str
    knowledge_base_ids: list[str]
    mcp_tools: list[AgentMcpToolRef]
    status: str
    published: bool
    created_by_user_id: str
    can_edit: bool
    created_at: datetime
    updated_at: datetime


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=8000)
    model_id: str = Field(min_length=1, max_length=36)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=4)
    mcp_tools: list[AgentMcpToolRef] = Field(default_factory=list, max_length=12)


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, max_length=8000)
    model_id: str | None = Field(default=None, min_length=1, max_length=36)
    knowledge_base_ids: list[str] | None = Field(default=None, max_length=4)
    mcp_tools: list[AgentMcpToolRef] | None = Field(default=None, max_length=12)
    status: str | None = Field(default=None, min_length=1, max_length=20)
    published: bool | None = None


class AgentRunCreateRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    preview: bool = False


class AgentPlanStepResponse(BaseModel):
    number: int
    title: str
    description: str
    status: Literal["pending", "completed", "failed"]


class AgentRunEventResponse(BaseModel):
    type: Literal["thought", "tool"] = "tool"
    turn: int
    tool_name: str
    status: Literal["running", "succeeded", "failed"]
    summary: str
    call_id: str = ""
    tool_label: str = ""
    tool_kind: Literal["knowledge", "mcp", "unknown"] = "unknown"
    server_name: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    reasoning: str = ""


class AgentRunResponse(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    requested_by_user_id: str
    goal: str
    model_id: str
    model_name: str
    status: str
    plan: list[AgentPlanStepResponse]
    events: list[AgentRunEventResponse]
    result: str
    last_error: str | None
    planned_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    trace_id: str = ""
