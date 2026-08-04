from datetime import datetime, timezone
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


class AgentRunCreateRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)


class AgentRunResumeRequest(BaseModel):
    decision: Literal["approved", "rejected"] | None = None


class AgentPlanStepResponse(BaseModel):
    id: str = ""
    number: int
    title: str
    description: str
    status: Literal["pending", "in_progress", "completed", "failed", "skipped"]
    result: str = ""


class AgentRunEventResponse(BaseModel):
    event_id: str = ""
    sequence: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: Literal["thought", "plan", "decision", "tool", "approval", "answer"]
    turn: int
    tool_name: str
    status: Literal["running", "succeeded", "failed", "approved", "rejected"]
    summary: str
    call_id: str = ""
    tool_label: str = ""
    tool_kind: Literal["knowledge", "mcp", "unknown"] = "unknown"
    server_name: str = ""
    input: Any = Field(default_factory=dict)
    output: Any = None


class AgentRunApprovalResponse(BaseModel):
    approval_id: str
    tool_name: str
    tool_label: str
    tool_kind: Literal["knowledge", "mcp", "unknown"]
    server_name: str
    input: Any


class AgentRunResponse(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    requested_by_user_id: str
    goal: str
    model_id: str
    model_name: str
    status: Literal[
        "planning",
        "planned",
        "running",
        "awaiting_approval",
        "succeeded",
        "failed",
    ]
    plan: list[AgentPlanStepResponse]
    plan_revision: int
    events: list[AgentRunEventResponse]
    pending_approval: AgentRunApprovalResponse | None
    budget: dict[str, Any]
    usage: dict[str, Any]
    result: str
    last_error: str | None
    stop_reason: str | None
    resumable: bool
    planned_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    trace_id: str = ""
