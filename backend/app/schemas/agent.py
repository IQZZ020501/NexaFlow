from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentMcpToolRef(BaseModel):
    server_id: str = Field(min_length=1, max_length=36)
    tool_name: str = Field(min_length=1, max_length=255)


KnowledgeQueryMode = Literal["required", "agentic"]


class AgentResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    instructions: str
    model_id: str
    knowledge_query_mode: KnowledgeQueryMode
    knowledge_base_ids: list[str]
    mcp_tools: list[AgentMcpToolRef]
    status: str
    published: bool
    published_by_user_id: str | None
    published_at: datetime | None
    created_by_user_id: str
    can_edit: bool
    created_at: datetime
    updated_at: datetime


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=8000)
    model_id: str = Field(min_length=1, max_length=36)
    knowledge_query_mode: KnowledgeQueryMode = "required"
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=4)
    mcp_tools: list[AgentMcpToolRef] = Field(default_factory=list, max_length=12)


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, max_length=8000)
    model_id: str | None = Field(default=None, min_length=1, max_length=36)
    knowledge_query_mode: KnowledgeQueryMode | None = None
    knowledge_base_ids: list[str] | None = Field(default=None, max_length=4)
    mcp_tools: list[AgentMcpToolRef] | None = Field(default=None, max_length=12)
    status: str | None = Field(default=None, min_length=1, max_length=20)
    published: bool | None = None


class AgentRunCreateRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=36)
    preview: bool = Field(
        default=False,
        description="Deprecated compatibility field; runs are always durable.",
    )


class ExternalAgentRunCreateRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=36)


class AgentApiDocumentationResponse(BaseModel):
    agent_id: str
    agent_name: str
    base_path: str


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
    duration_ms: int = 0
    reasoning: str = ""


class AgentRunResponse(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    requested_by_user_id: str | None
    conversation_id: str
    goal: str
    model_id: str
    model_name: str
    knowledge_query_mode: KnowledgeQueryMode
    status: str
    plan: list[AgentPlanStepResponse]
    events: list[AgentRunEventResponse]
    result: str
    model_usage: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None
    planned_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    trace_id: str = ""


class AgentToolCallResponse(BaseModel):
    call_id: str
    turn: int
    tool_name: str
    tool_kind: Literal["knowledge", "mcp", "unknown"]
    server_name: str
    arguments: dict[str, Any]
    status: Literal[
        "pending",
        "awaiting_approval",
        "approved",
        "running",
        "succeeded",
        "failed",
        "rejected",
        "uncertain",
    ]
    approval_required: bool
    last_error: str | None
    approved_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class AgentApiCredentialCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AgentApiCredentialResponse(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    name: str
    hint: str
    created_by_user_id: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class AgentApiCredentialListResponse(BaseModel):
    items: list[AgentApiCredentialResponse]


class AgentApiCredentialCreateResponse(BaseModel):
    credential: AgentApiCredentialResponse
    token: str


class PublicAgentProfileResponse(BaseModel):
    id: str
    name: str
    description: str


class ExternalAgentKnowledgeHitResponse(BaseModel):
    knowledge_base: str = ""
    document: str = ""
    content: str = ""


class ExternalAgentProgressEventResponse(BaseModel):
    id: str
    type: Literal["analysis", "knowledge", "tool", "answer"]
    status: Literal["running", "succeeded", "failed"]
    stage: Literal[
        "analyzing",
        "reviewing",
        "completed",
        "running",
        "succeeded",
        "failed",
    ]
    turn: int
    count: int | None = None
    reasoning: str = ""
    hits: list[ExternalAgentKnowledgeHitResponse] = Field(default_factory=list)


class ExternalAgentRunResponse(BaseModel):
    id: str
    conversation_id: str
    question: str
    status: str
    result: str
    error: str | None
    progress: list[ExternalAgentProgressEventResponse]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class ExternalAgentRunListResponse(BaseModel):
    items: list[ExternalAgentRunResponse]
    total: int
    offset: int
    limit: int


class PublicAgentConversationResponse(BaseModel):
    conversation_id: str
    question: str
    status: str
    result: str
    run_count: int
    created_at: datetime
    updated_at: datetime


class PublicAgentConversationListResponse(BaseModel):
    items: list[PublicAgentConversationResponse]


class AgentLogResponse(BaseModel):
    id: str
    conversation_id: str
    access_source: Literal["console", "public", "api"]
    consumer_id: str
    display_name: str
    requested_by_user_id: str | None
    execution_user_id: str
    question: str
    status: str
    result: str
    last_error: str | None
    model_usage: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class AgentLogListResponse(BaseModel):
    items: list[AgentLogResponse]
    total: int
    offset: int
    limit: int


class AgentConversationUserResponse(BaseModel):
    consumer_id: str
    access_source: Literal["console", "public", "api"]
    display_name: str
    first_seen_at: datetime
    last_seen_at: datetime
    conversation_count: int
    run_count: int


class AgentConversationUserListResponse(BaseModel):
    items: list[AgentConversationUserResponse]
    total: int
    offset: int
    limit: int


class AgentMonitoringValues(BaseModel):
    active_users: int
    conversations: int
    runs: int
    succeeded: int
    failed: int
    total_tokens: int


class AgentMonitoringDailyResponse(AgentMonitoringValues):
    date: date


class AgentMonitoringResponse(BaseModel):
    days: Literal[7, 30, 90]
    summary: AgentMonitoringValues
    daily: list[AgentMonitoringDailyResponse]
