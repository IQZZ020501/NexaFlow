from dataclasses import replace
from datetime import datetime

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.agents.models import Agent as AgentOrm
from app.domain.agents.models import AgentRun as AgentRunOrm
from app.domain.agents.models import AgentRunState as AgentRunStateOrm
from app.domain.knowledge.models import KnowledgeBase as KnowledgeBaseOrm
from app.domain.knowledge.models import KnowledgeDocument as KnowledgeDocumentOrm
from app.domain.knowledge.models import (
    KnowledgeDocumentChunk as KnowledgeDocumentChunkOrm,
)
from app.domain.models.registered import RegisteredModel as RegisteredModelOrm
from app.domain.platform.models import Team as TeamOrm
from app.domain.platform.models import TeamMembership as TeamMembershipOrm
from app.domain.platform.models import User as UserOrm
from app.domain.platform.models import WorkspaceMembership as WorkspaceMembershipOrm
from app.domain.tools.models import Tool as ToolOrm
from app.domain.tools.models import ToolInvocation as ToolInvocationOrm
from app.domain.tools.models import ToolVersion as ToolVersionOrm
from app.domain.tools.runtime import (
    TOOL_INVOCATION_FAILED,
    TOOL_INVOCATION_SUCCEEDED,
    TOOL_INVOCATION_UNCERTAIN,
)
from app.domain.workflows.models import WorkflowRunDetail as WorkflowRunDetailOrm
from app.entities.analytics import (
    WorkspaceAnalyticsCounts,
    WorkspaceAnalyticsInventory,
    WorkspaceAnalyticsInventoryApplications,
    WorkspaceAnalyticsInventoryKnowledge,
    WorkspaceAnalyticsInventoryTools,
    WorkspaceAnalyticsRun,
    WorkspaceAnalyticsTeamMember,
    WorkspaceAnalyticsToolCall,
    WorkspaceAnalyticsToolCallSummary,
)
from app.infra.db.repositories.tools.inventory import (
    tool_catalog_conditions,
    tool_inventory_resources,
)


async def get_workspace_analytics_counts(
    db: AsyncSession,
    workspace_id: str,
) -> WorkspaceAnalyticsCounts:
    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.sum(
                    case((UserOrm.is_active.is_(True), 1), else_=0)
                ).label("active"),
                select(func.count())
                .select_from(TeamOrm)
                .where(
                    TeamOrm.workspace_id == workspace_id,
                    TeamOrm.status == "active",
                )
                .scalar_subquery()
                .label("active_teams"),
            )
            .select_from(WorkspaceMembershipOrm)
            .join(UserOrm, UserOrm.id == WorkspaceMembershipOrm.user_id)
            .where(WorkspaceMembershipOrm.workspace_id == workspace_id)
        )
    ).one()
    return WorkspaceAnalyticsCounts(
        members_total=int(row.total or 0),
        members_active=int(row.active or 0),
        active_teams=int(row.active_teams or 0),
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
            AgentRunStateOrm.status,
            AgentRunOrm.goal,
            AgentRunStateOrm.model_usage,
            WorkflowRunDetailOrm.token_usage.label("workflow_token_usage"),
            AgentRunStateOrm.started_at,
            AgentRunStateOrm.finished_at,
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
        .join(
            AgentRunStateOrm,
            and_(
                AgentRunStateOrm.workspace_id == AgentRunOrm.workspace_id,
                AgentRunStateOrm.run_id == AgentRunOrm.id,
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


async def list_workspace_analytics_previous_runs(
    db: AsyncSession,
    workspace_id: str,
    start_at: datetime,
    end_at: datetime,
) -> list[WorkspaceAnalyticsRun]:
    """Load only the columns needed to summarize the previous comparison window."""
    rows = await db.execute(
        select(
            AgentRunOrm.id,
            AgentRunOrm.requested_by_user_id,
            AgentRunOrm.access_source,
            AgentRunStateOrm.status,
            AgentRunStateOrm.model_usage,
            WorkflowRunDetailOrm.token_usage.label("workflow_token_usage"),
            AgentRunStateOrm.started_at,
            AgentRunStateOrm.finished_at,
        )
        .select_from(AgentRunOrm)
        .join(
            AgentRunStateOrm,
            and_(
                AgentRunStateOrm.workspace_id == AgentRunOrm.workspace_id,
                AgentRunStateOrm.run_id == AgentRunOrm.id,
            ),
        )
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
    )
    return [
        WorkspaceAnalyticsRun(
            id=row.id,
            requested_by_user_id=row.requested_by_user_id,
            access_source=row.access_source,
            status=row.status,
            model_usage=dict(row.model_usage or {}),
            workflow_token_usage=row.workflow_token_usage,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
        for row in rows.all()
    ]


async def list_workspace_analytics_tool_calls(
    db: AsyncSession,
    workspace_id: str,
    start_at: datetime,
    end_at: datetime,
) -> list[WorkspaceAnalyticsToolCall]:
    # A tool is reported only while the workspace catalog still lists it, so
    # re-registered MCP servers and archived probes keep their history out of
    # the ranking unless an active tool with the same key exists.
    active_tool = aliased(ToolOrm)
    rows = await db.execute(
        select(
            ToolInvocationOrm.id,
            ToolInvocationOrm.tool_id,
            ToolInvocationOrm.status,
            ToolInvocationOrm.approved_by_user_id,
            ToolInvocationOrm.created_at,
            ToolOrm.kind.label("tool_kind"),
            ToolVersionOrm.display_name.label("tool_display_name"),
            ToolOrm.function_name.label("tool_function_name"),
        )
        .select_from(ToolInvocationOrm)
        .outerjoin(
            ToolOrm,
            and_(
                ToolOrm.workspace_id == ToolInvocationOrm.workspace_id,
                ToolOrm.id == ToolInvocationOrm.tool_id,
            ),
        )
        .outerjoin(
            ToolVersionOrm,
            and_(
                ToolVersionOrm.workspace_id == ToolInvocationOrm.workspace_id,
                ToolVersionOrm.id == ToolInvocationOrm.tool_version_id,
            ),
        )
        .where(
            ToolInvocationOrm.workspace_id == workspace_id,
            # Agent-internal ledger entries carry no catalog tool reference and
            # would otherwise double-count agent steps as tool usage.
            ToolInvocationOrm.tool_id.is_not(None),
            select(active_tool.id)
            .where(
                *tool_catalog_conditions(workspace_id, tool=active_tool),
                active_tool.stable_key == ToolOrm.stable_key,
            )
            .exists(),
            ToolInvocationOrm.created_at >= start_at,
            ToolInvocationOrm.created_at < end_at,
        )
        .order_by(ToolInvocationOrm.created_at, ToolInvocationOrm.id)
    )
    return [
        WorkspaceAnalyticsToolCall(
            id=row.id,
            tool_id=row.tool_id or "",
            tool_name=row.tool_display_name
            or row.tool_function_name
            or row.tool_id
            or "",
            tool_kind=row.tool_kind or "unknown",
            status=row.status or "",
            approved=row.approved_by_user_id is not None,
            created_at=row.created_at,
        )
        for row in rows.all()
    ]


async def get_workspace_analytics_tool_call_summary(
    db: AsyncSession,
    workspace_id: str,
    start_at: datetime,
    end_at: datetime,
) -> WorkspaceAnalyticsToolCallSummary:
    """Aggregate tool invocation counts for the previous comparison window."""
    active_tool = aliased(ToolOrm)
    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ToolInvocationOrm.status == TOOL_INVOCATION_SUCCEEDED,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("succeeded"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ToolInvocationOrm.status.in_(
                                    (
                                        TOOL_INVOCATION_FAILED,
                                        TOOL_INVOCATION_UNCERTAIN,
                                    )
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("failed"),
            )
            .select_from(ToolInvocationOrm)
            .outerjoin(
                ToolOrm,
                and_(
                    ToolOrm.workspace_id == ToolInvocationOrm.workspace_id,
                    ToolOrm.id == ToolInvocationOrm.tool_id,
                ),
            )
            .where(
                ToolInvocationOrm.workspace_id == workspace_id,
                ToolInvocationOrm.tool_id.is_not(None),
                select(active_tool.id)
                .where(
                    *tool_catalog_conditions(workspace_id, tool=active_tool),
                    active_tool.stable_key == ToolOrm.stable_key,
                )
                .exists(),
                ToolInvocationOrm.created_at >= start_at,
                ToolInvocationOrm.created_at < end_at,
            )
        )
    ).one()
    return WorkspaceAnalyticsToolCallSummary(
        total=int(row.total or 0),
        succeeded=int(row.succeeded or 0),
        failed=int(row.failed or 0),
    )


async def get_workspace_analytics_inventory(
    db: AsyncSession,
    workspace_id: str,
) -> WorkspaceAnalyticsInventory:
    application_rows = (
        await db.execute(
            select(
                AgentOrm.app_type,
                AgentOrm.status,
                AgentOrm.published,
                func.count().label("total"),
            )
            .where(AgentOrm.workspace_id == workspace_id)
            .group_by(AgentOrm.app_type, AgentOrm.status, AgentOrm.published)
        )
    ).all()
    applications = WorkspaceAnalyticsInventoryApplications()
    for row in application_rows:
        total = int(row.total or 0)
        applications = replace(
            applications,
            total=applications.total + total,
            agents=applications.agents
            + (total if row.app_type == "agent" else 0),
            workflows=applications.workflows
            + (total if row.app_type == "workflow" else 0),
            published=applications.published + (total if row.published else 0),
            active=applications.active
            + (total if row.status == "active" else 0),
        )

    scalar_counts = (
        await db.execute(
            select(
                select(func.count())
                .select_from(KnowledgeBaseOrm)
                .where(KnowledgeBaseOrm.workspace_id == workspace_id)
                .scalar_subquery()
                .label("knowledge_bases"),
                select(func.count())
                .select_from(KnowledgeDocumentOrm)
                .where(
                    KnowledgeDocumentOrm.workspace_id == workspace_id,
                    KnowledgeDocumentOrm.is_active.is_(True),
                )
                .scalar_subquery()
                .label("knowledge_documents"),
                select(func.count())
                .select_from(KnowledgeDocumentChunkOrm)
                .where(KnowledgeDocumentChunkOrm.workspace_id == workspace_id)
                .scalar_subquery()
                .label("knowledge_chunks"),
                select(func.count())
                .select_from(RegisteredModelOrm)
                .where(RegisteredModelOrm.workspace_id == workspace_id)
                .scalar_subquery()
                .label("models"),
            )
        )
    ).one()

    tool_resources = tool_inventory_resources(workspace_id)
    tool_rows = (
        await db.execute(
            select(
                tool_resources.c.kind,
                tool_resources.c.status,
                func.count().label("total"),
            )
            .group_by(tool_resources.c.kind, tool_resources.c.status)
        )
    ).all()
    tools = WorkspaceAnalyticsInventoryTools()
    for row in tool_rows:
        total = int(row.total or 0)
        tools = replace(
            tools,
            total=tools.total + total,
            mcp=tools.mcp + (total if row.kind == "mcp" else 0),
            builtin=tools.builtin + (total if row.kind == "builtin" else 0),
            active=tools.active + (total if row.status == "active" else 0),
        )

    return WorkspaceAnalyticsInventory(
        applications=applications,
        knowledge=WorkspaceAnalyticsInventoryKnowledge(
            bases=int(scalar_counts.knowledge_bases or 0),
            documents=int(scalar_counts.knowledge_documents or 0),
            chunks=int(scalar_counts.knowledge_chunks or 0),
        ),
        tools=tools,
        models=int(scalar_counts.models or 0),
    )
