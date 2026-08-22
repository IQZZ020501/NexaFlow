from datetime import datetime

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.team import Team as TeamOrm
from app.domain.team import TeamMembership as TeamMembershipOrm
from app.domain.user import User as UserOrm
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipOrm
from app.entities.analytics import (
    WorkspaceAnalyticsCounts,
    WorkspaceAnalyticsGraphBuild,
    WorkspaceAnalyticsRun,
    WorkspaceAnalyticsTeamMember,
)
from app.shareddomain.agents.models import Agent as AgentOrm
from app.shareddomain.agents.models import AgentRun as AgentRunOrm
from app.shareddomain.knowledge_graph.models import (
    KnowledgeGraphRevision as KnowledgeGraphRevisionOrm,
)
from app.shareddomain.workflows.models import WorkflowRunDetail as WorkflowRunDetailOrm


async def get_workspace_analytics_counts(
    db: AsyncSession,
    workspace_id: str,
) -> WorkspaceAnalyticsCounts:
    member_counts = (
        await db.execute(
            select(
                func.count().label("total"),
                func.sum(
                    case((UserOrm.is_active.is_(True), 1), else_=0)
                ).label("active"),
            )
            .select_from(WorkspaceMembershipOrm)
            .join(UserOrm, UserOrm.id == WorkspaceMembershipOrm.user_id)
            .where(WorkspaceMembershipOrm.workspace_id == workspace_id)
        )
    ).one()
    active_teams = await db.scalar(
        select(func.count())
        .select_from(TeamOrm)
        .where(
            TeamOrm.workspace_id == workspace_id,
            TeamOrm.status == "active",
        )
    )
    return WorkspaceAnalyticsCounts(
        members_total=int(member_counts.total or 0),
        members_active=int(member_counts.active or 0),
        active_teams=int(active_teams or 0),
    )


async def list_workspace_analytics_team_members(
    db: AsyncSession,
    workspace_id: str,
) -> list[WorkspaceAnalyticsTeamMember]:
    rows = await db.execute(
        select(
            TeamOrm.id.label("team_id"),
            TeamOrm.name.label("team_name"),
            TeamMembershipOrm.user_id,
        )
        .select_from(TeamMembershipOrm)
        .join(
            TeamOrm,
            and_(
                TeamOrm.workspace_id == TeamMembershipOrm.workspace_id,
                TeamOrm.id == TeamMembershipOrm.team_id,
            ),
        )
        .where(
            TeamMembershipOrm.workspace_id == workspace_id,
            TeamOrm.status == "active",
        )
        .order_by(TeamOrm.name, TeamOrm.id, TeamMembershipOrm.user_id)
    )
    return [
        WorkspaceAnalyticsTeamMember(
            team_id=row.team_id,
            team_name=row.team_name,
            user_id=row.user_id,
        )
        for row in rows.all()
    ]


async def list_workspace_analytics_runs(
    db: AsyncSession,
    workspace_id: str,
    start_at: datetime,
    end_at: datetime,
) -> list[WorkspaceAnalyticsRun]:
    rows = await db.execute(
        select(
            AgentRunOrm.id,
            AgentRunOrm.agent_id,
            AgentOrm.name.label("application_name"),
            AgentOrm.app_type,
            AgentRunOrm.requested_by_user_id,
            UserOrm.username.label("requester_username"),
            UserOrm.name.label("requester_name"),
            AgentRunOrm.access_source,
            AgentRunOrm.status,
            AgentRunOrm.goal,
            AgentRunOrm.model_usage,
            WorkflowRunDetailOrm.token_usage.label("workflow_token_usage"),
            AgentRunOrm.started_at,
            AgentRunOrm.finished_at,
            AgentRunOrm.created_at,
        )
        .select_from(AgentRunOrm)
        .join(
            AgentOrm,
            and_(
                AgentOrm.workspace_id == AgentRunOrm.workspace_id,
                AgentOrm.id == AgentRunOrm.agent_id,
            ),
        )
        .outerjoin(UserOrm, UserOrm.id == AgentRunOrm.requested_by_user_id)
        .outerjoin(
            WorkflowRunDetailOrm,
            and_(
                WorkflowRunDetailOrm.workspace_id == AgentRunOrm.workspace_id,
                WorkflowRunDetailOrm.run_id == AgentRunOrm.id,
            ),
        )
        .where(
            AgentRunOrm.workspace_id == workspace_id,
            AgentRunOrm.depth == 0,
            AgentRunOrm.created_at >= start_at,
            AgentRunOrm.created_at < end_at,
        )
        .order_by(AgentRunOrm.created_at, AgentRunOrm.id)
    )
    return [
        WorkspaceAnalyticsRun(
            id=row.id,
            agent_id=row.agent_id,
            application_name=row.application_name,
            app_type=row.app_type,
            requested_by_user_id=row.requested_by_user_id,
            requester_username=row.requester_username,
            requester_name=row.requester_name,
            access_source=row.access_source,
            status=row.status,
            goal=row.goal,
            model_usage=dict(row.model_usage or {}),
            workflow_token_usage=row.workflow_token_usage,
            started_at=row.started_at,
            finished_at=row.finished_at,
            created_at=row.created_at,
        )
        for row in rows.all()
    ]


async def list_workspace_analytics_graph_builds(
    db: AsyncSession,
    workspace_id: str,
    start_at: datetime,
    end_at: datetime,
) -> list[WorkspaceAnalyticsGraphBuild]:
    rows = await db.execute(
        select(
            KnowledgeGraphRevisionOrm.id,
            KnowledgeGraphRevisionOrm.status,
            KnowledgeGraphRevisionOrm.model_usage_json,
            KnowledgeGraphRevisionOrm.created_at,
        )
        .where(
            KnowledgeGraphRevisionOrm.workspace_id == workspace_id,
            KnowledgeGraphRevisionOrm.created_at >= start_at,
            KnowledgeGraphRevisionOrm.created_at < end_at,
        )
        .order_by(
            KnowledgeGraphRevisionOrm.created_at,
            KnowledgeGraphRevisionOrm.id,
        )
    )
    return [
        WorkspaceAnalyticsGraphBuild(
            id=row.id,
            status=row.status,
            model_usage=dict(row.model_usage_json or {}),
            created_at=row.created_at,
        )
        for row in rows.all()
    ]
