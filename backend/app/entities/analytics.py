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
