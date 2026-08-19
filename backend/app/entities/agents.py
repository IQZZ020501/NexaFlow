from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class Agent:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    name: str = ""
    app_type: str = "agent"
    description: str = ""
    interaction_config: dict[str, Any] = field(default_factory=dict)
    instructions: str = ""
    model_id: str = ""
    knowledge_query_mode: str = "required"
    status: str = "active"
    published: bool = False
    published_snapshot: dict[str, Any] | None = None
    current_published_version_id: str | None = None
    published_by_user_id: str | None = None
    published_at: datetime | None = None
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class AgentPublicationVersion:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    agent_id: str = ""
    version_number: int = 1
    schema_version: int = 1
    configuration_snapshot: dict[str, Any] = field(default_factory=dict)
    resource_snapshot: dict[str, Any] = field(default_factory=dict)
    configuration_hash: str = ""
    published_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class AgentKnowledgeBase:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    agent_id: str = ""
    knowledge_base_id: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class AgentMcpTool:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    agent_id: str = ""
    mcp_server_id: str = ""
    tool_name: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class AgentApiCredential:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    agent_id: str = ""
    name: str = ""
    token_hash: str = ""
    hint: str = ""
    created_by_user_id: str = ""
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class AgentRun:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    agent_id: str = ""
    requested_by_user_id: str | None = None
    execution_user_id: str = ""
    access_source: str = "console"
    consumer_id: str = ""
    conversation_id: str = field(default_factory=new_id)
    root_run_id: str = ""
    parent_run_id: str | None = None
    parent_node_id: str | None = None
    regenerated_from_run_id: str | None = None
    depth: int = 0
    goal: str = ""
    attachment_context: str = ""
    instructions: str = ""
    knowledge_base_ids: list[str] = field(default_factory=list)
    knowledge_query_mode: str = "required"
    mcp_tools: list[dict[str, str]] = field(default_factory=list)
    snapshot_schema_version: int = 1
    configuration_source: str = "legacy"
    agent_publication_version_id: str | None = None
    application_snapshot: dict[str, Any] = field(default_factory=dict)
    application_snapshot_hash: str = ""
    tool_snapshots: list[dict[str, Any]] = field(default_factory=list)
    model_id: str = ""
    model_name: str = ""
    status: str = "queued"
    attempts: int = 0
    max_attempts: int = 3
    worker_task_id: str | None = None
    lease_expires_at: datetime | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    checkpoint_phase: str = "agent"
    grounding_status: str = "not_started"
    grounding_meta: dict[str, Any] = field(default_factory=dict)
    feedback: str | None = None
    feedback_updated_at: datetime | None = None
    trace_id: str = ""
    plan: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: str = ""
    context_summary: str = ""
    model_usage: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    planned_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.root_run_id = self.root_run_id or self.parent_run_id or self.id
        if self.access_source == "console" and self.requested_by_user_id:
            self.execution_user_id = self.execution_user_id or self.requested_by_user_id
            self.consumer_id = self.consumer_id or self.requested_by_user_id


@dataclass
class AgentRunEvent:
    id: int | None = None
    workspace_id: str = ""
    run_id: str = ""
    event: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class AgentToolCall:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    run_id: str = ""
    turn: int = 0
    call_id: str = ""
    tool_name: str = ""
    tool_kind: str = "unknown"
    server_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    arguments_hash: str = ""
    definition_hash: str = ""
    policy_mode: str = ""
    idempotency_key: str = ""
    status: str = "pending"
    approval_required: bool = False
    approved_by_user_id: str | None = None
    approved_at: datetime | None = None
    worker_task_id: str | None = None
    lease_expires_at: datetime | None = None
    result_content: str = ""
    result_summary: str = ""
    result_output: Any = None
    result_is_error: bool = False
    result_evidence_ids: list[str] = field(default_factory=list)
    last_error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
