from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class WorkflowDefinition:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    agent_id: str = ""
    revision: int = 1
    graph: dict[str, Any] = field(default_factory=dict)
    graph_hash: str = ""
    updated_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class WorkflowVersion:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    agent_id: str = ""
    definition_id: str = ""
    definition_revision: int = 1
    version_number: int = 1
    default_model_id: str = ""
    graph: dict[str, Any] = field(default_factory=dict)
    graph_hash: str = ""
    published_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class WorkflowRunDetail:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    run_id: str = ""
    definition_id: str = ""
    definition_revision: int = 1
    version_id: str | None = None
    version_number: int | None = None
    source: str = "draft"
    graph_hash: str = ""
    graph_snapshot: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    max_steps: int = 100
    max_model_tokens: int = 100000
    deadline_at: datetime = field(default_factory=utc_now)
    step_count: int = 0
    token_usage: int = 0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class WorkflowNodeExecution:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    run_id: str = ""
    node_id: str = ""
    node_type: str = ""
    status: str = "pending"
    sequence: int = 0
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    model_usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
