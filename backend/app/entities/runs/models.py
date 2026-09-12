"""Pure run entities shared by Agent and Workflow execution.

Run identity, lineage and event records span both runtimes (workflow rows
live in the same tables), so their dataclasses live here instead of inside
the agents feature.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.entities.defaults import new_id, utc_now


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
    mcp_tools: list[dict[str, str]] = field(default_factory=list)
    snapshot_schema_version: int = 1
    configuration_source: str = "legacy"
    agent_publication_version_id: str | None = None
    application_snapshot: dict[str, Any] = field(default_factory=dict)
    application_snapshot_hash: str = ""
    tool_snapshots: list[dict[str, Any]] = field(default_factory=list)
    model_id: str = ""
    model_name: str = ""
    max_runtime_seconds: float = 300.0
    max_turns: int = 8
    max_tool_calls: int = 12
    max_knowledge_calls: int = 6
    max_knowledge_rounds: int = 3
    max_model_tokens: int = 100_000
    model_runtime_snapshot: dict[str, Any] = field(default_factory=dict)
    knowledge_resource_snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    attempts: int = 0
    max_attempts: int = 3
    worker_task_id: str | None = None
    lease_expires_at: datetime | None = None
    execution_deadline_at: datetime | None = None
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
