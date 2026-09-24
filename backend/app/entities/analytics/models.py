from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WorkspaceAnalyticsCounts:
    members_total: int = 0
    members_active: int = 0
    active_teams: int = 0


@dataclass(frozen=True)
class WorkspaceAnalyticsTeamMember:
    team_id: str = ""
    team_name: str = ""
    user_id: str = ""


@dataclass(frozen=True)
class WorkspaceAnalyticsRun:
    id: str = ""
    agent_id: str = ""
    application_name: str = ""
    app_type: str = "agent"
    requested_by_user_id: str | None = None
    requester_username: str | None = None
    requester_name: str | None = None
    access_source: str = "console"
    status: str = "queued"
    goal: str = ""
    model_usage: dict[str, Any] = field(default_factory=dict)
    workflow_token_usage: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class WorkspaceAnalyticsGraphBuild:
    id: str = ""
    status: str = "building"
    model_usage: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class WorkspaceAnalyticsInventoryApplications:
    total: int = 0
    agents: int = 0
    workflows: int = 0
    published: int = 0
    active: int = 0


@dataclass(frozen=True)
class WorkspaceAnalyticsInventoryKnowledge:
    bases: int = 0
    documents: int = 0
    chunks: int = 0


@dataclass(frozen=True)
class WorkspaceAnalyticsInventoryTools:
    total: int = 0
    mcp: int = 0
    python: int = 0
    builtin: int = 0
    active: int = 0


@dataclass(frozen=True)
class WorkspaceAnalyticsInventory:
    applications: WorkspaceAnalyticsInventoryApplications = field(
        default_factory=WorkspaceAnalyticsInventoryApplications
    )
    knowledge: WorkspaceAnalyticsInventoryKnowledge = field(
        default_factory=WorkspaceAnalyticsInventoryKnowledge
    )
    tools: WorkspaceAnalyticsInventoryTools = field(
        default_factory=WorkspaceAnalyticsInventoryTools
    )
    models: int = 0


@dataclass(frozen=True)
class WorkspaceAnalyticsToolCall:
    id: str = ""
    tool_id: str = ""
    tool_name: str = ""
    tool_kind: str = ""
    status: str = ""
    approved: bool = False
    created_at: datetime | None = None
