from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class AnalyticsCountComparison(BaseModel):
    value: int
    previous_value: int
    change_percent: float | None


class AnalyticsRatioComparison(BaseModel):
    value: float | None
    previous_value: float | None
    change_percent: float | None


class WorkspaceAnalyticsMemberSummary(BaseModel):
    total: int
    active: int


class WorkspaceAnalyticsTokenSummary(BaseModel):
    input: int
    output: int
    application_total: int
    graph_total: int
    total: int
    unreported_runs: int
    unreported_graph_builds: int
    previous_total: int
    change_percent: float | None


class WorkspaceAnalyticsSummary(BaseModel):
    members: WorkspaceAnalyticsMemberSummary
    active_teams: int
    active_users: AnalyticsCountComparison
    runs: AnalyticsCountComparison
    tokens: WorkspaceAnalyticsTokenSummary
    success_rate: AnalyticsRatioComparison
    average_duration_ms: AnalyticsRatioComparison


class WorkspaceAnalyticsTrendPoint(BaseModel):
    date: date
    runs: int
    graph_builds: int
    input_tokens: int
    output_tokens: int
    application_tokens: int
    graph_tokens: int
    total_tokens: int


class WorkspaceAnalyticsHourlyPoint(BaseModel):
    hour: int = Field(ge=0, le=23)
    runs: int


class WorkspaceAnalyticsDistributionItem(BaseModel):
    key: str
    count: int


class WorkspaceAnalyticsDistributions(BaseModel):
    run_types: list[WorkspaceAnalyticsDistributionItem]
    access_sources: list[WorkspaceAnalyticsDistributionItem]
    statuses: list[WorkspaceAnalyticsDistributionItem]


class WorkspaceAnalyticsUserRankingItem(BaseModel):
    user_id: str
    name: str
    run_count: int
    total_tokens: int


class WorkspaceAnalyticsApplicationRankingItem(BaseModel):
    application_id: str
    name: str
    app_type: Literal["agent", "workflow"]
    run_count: int
    total_tokens: int
    success_rate: float | None


class WorkspaceAnalyticsAnonymousUsage(BaseModel):
    run_count: int
    total_tokens: int


class WorkspaceAnalyticsTeamRankingItem(BaseModel):
    team_id: str
    name: str
    peak_daily_runs: int
    run_count: int


class WorkspaceAnalyticsRankings(BaseModel):
    users: list[WorkspaceAnalyticsUserRankingItem]
    applications: list[WorkspaceAnalyticsApplicationRankingItem]
    anonymous: WorkspaceAnalyticsAnonymousUsage
    teams: list[WorkspaceAnalyticsTeamRankingItem]


class WorkspaceAnalyticsFrequentQuestion(BaseModel):
    question: str
    count: int
    latest_at: datetime


class WorkspaceAnalyticsMetadata(BaseModel):
    workspace_id: str
    timezone: Literal["Asia/Shanghai"]
    from_date: date
    to_date: date
    previous_from_date: date
    previous_to_date: date
    end_exclusive: Literal[True]
    generated_at: datetime


class WorkspaceAnalyticsResponse(BaseModel):
    summary: WorkspaceAnalyticsSummary
    trends: list[WorkspaceAnalyticsTrendPoint]
    hourly_runs: list[WorkspaceAnalyticsHourlyPoint]
    distributions: WorkspaceAnalyticsDistributions
    rankings: WorkspaceAnalyticsRankings
    frequent_questions: list[WorkspaceAnalyticsFrequentQuestion]
    metadata: WorkspaceAnalyticsMetadata
