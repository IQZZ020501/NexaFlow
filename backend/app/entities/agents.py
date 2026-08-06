from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infrastructure.model_utils import new_id, utc_now


@dataclass
class Agent:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    name: str = ""
    description: str = ""
    instructions: str = ""
    model_id: str = ""
    status: str = "active"
    published: bool = False
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


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
class AgentRun:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    agent_id: str = ""
    requested_by_user_id: str = ""
    goal: str = ""
    instructions: str = ""
    knowledge_base_ids: list[str] = field(default_factory=list)
    mcp_tools: list[dict[str, str]] = field(default_factory=list)
    model_id: str = ""
    model_name: str = ""
    status: str = "planning"
    plan: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: str = ""
    last_error: str | None = None
    planned_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
