from datetime import datetime

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.llm.models import RegisteredModel
from app.shareddomain.platform.models import Team as TeamOrm
from app.shareddomain.platform.models import User as UserOrm
from app.shareddomain.platform.models import WorkspaceMembership as WorkspaceMembershipOrm
from app.infrastructure.system_log import SystemLog
from app.shareddomain.agents.models import (
    AGENT_RUN_ACTIVE_STATUSES,
    AGENT_RUN_FAILED_STATUS,
    AGENT_RUN_LEGACY_CLAIMABLE_STATUSES,
    AGENT_RUN_UNIFIED_CLAIMABLE_STATUSES,
    Agent as AgentOrm,
    AgentRun as AgentRunOrm,
    AgentRunState as AgentRunStateOrm,
)
from app.shareddomain.knowledge.models import KnowledgeBase as KnowledgeBaseOrm
from app.shareddomain.knowledge.models import KnowledgeTask as KnowledgeTaskOrm
from app.shareddomain.knowledge_graph.models import (
    KnowledgeGraphRevision as KnowledgeGraphRevisionOrm,
)
from app.shareddomain.tools.models import Tool as ToolOrm
from app.shareddomain.workflows.models import WorkflowDefinition as WorkflowDefinitionOrm


async def _count(db: AsyncSession, model: type, workspace_id: str, *conditions) -> int:
    """Count records for a model within a workspace, optionally applying additional conditions.
    
    Parameters:
    	db (AsyncSession): Database session used to execute the count query.
    	model (type): Model whose workspace records are counted.
    	workspace_id (str): Identifier of the workspace to filter by.
    	*conditions: Additional query conditions to apply.
    
    Returns:
    	int: The number of matching records.
    """
    statement = select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
    if conditions:
        statement = statement.where(*conditions)
    return int(await db.scalar(statement) or 0)


async def workspace_inventory_counts(
    db: AsyncSession,
    workspace_id: str,
    day_ago: datetime,
) -> dict[str, int]:
    """
    Aggregate workspace inventory, activity, and recent failure metrics.
    
    Parameters:
        workspace_id (str): Identifier of the workspace to summarize.
        day_ago (datetime): Lower time boundary for failures counted from the previous 24-hour interval.
    
    Returns:
        dict[str, int]: Workspace metrics, including member, team, resource, active-run, and recent failure counts.
    """
    member_row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.sum(case((UserOrm.is_active.is_(True), 1), else_=0)).label("active"),
            )
            .select_from(WorkspaceMembershipOrm)
            .join(UserOrm, UserOrm.id == WorkspaceMembershipOrm.user_id)
            .where(WorkspaceMembershipOrm.workspace_id == workspace_id)
        )
    ).one()
    failed_runs_24h = int(
        await db.scalar(
            select(func.count())
            .select_from(AgentRunStateOrm)
            .join(
                AgentRunOrm,
                and_(
                    AgentRunOrm.workspace_id == AgentRunStateOrm.workspace_id,
                    AgentRunOrm.id == AgentRunStateOrm.run_id,
                ),
            )
            .where(
                AgentRunStateOrm.workspace_id == workspace_id,
                AgentRunStateOrm.status == AGENT_RUN_FAILED_STATUS,
                AgentRunOrm.created_at >= day_ago,
            )
        )
        or 0
    )
    return {
        "members_total": int(member_row.total or 0),
        "members_active": int(member_row.active or 0),
        "teams_total": await _count(db, TeamOrm, workspace_id),
        "teams_active": await _count(db, TeamOrm, workspace_id, TeamOrm.status == "active"),
        "agents_total": await _count(db, AgentOrm, workspace_id),
        "knowledge_bases_total": await _count(db, KnowledgeBaseOrm, workspace_id),
        "models_total": await _count(db, RegisteredModel, workspace_id),
        "tools_total": await _count(db, ToolOrm, workspace_id),
        "workflows_total": await _count(db, WorkflowDefinitionOrm, workspace_id),
        "active_runs": await _count(
            db,
            AgentRunStateOrm,
            workspace_id,
            AgentRunStateOrm.status.in_(AGENT_RUN_ACTIVE_STATUSES),
        ),
        "failed_runs_24h": failed_runs_24h,
        "failed_tasks_24h": await _count(
            db, KnowledgeTaskOrm, workspace_id,
            KnowledgeTaskOrm.status == "failed", KnowledgeTaskOrm.created_at >= day_ago,
        ),
    }


async def health_counts(
    db: AsyncSession,
    since: datetime,
) -> tuple[int, int, int, int, int]:
    """
    Count pending knowledge tasks and agent runs, along with recent error and critical system logs.
    
    Parameters:
        since (datetime): Start time for counting system logs.
    
    Returns:
        tuple[int, int, int, int, int]: Pending work, recent failed logs,
        pending Graph tasks, recent failed Graph tasks, and Graph profile repairs.
    """
    pending = int(
        await db.scalar(
            select(func.count()).select_from(KnowledgeTaskOrm).where(
                KnowledgeTaskOrm.status.in_({"queued", "running"})
            )
        )
        or 0
    )
    pending += int(
        await db.scalar(
            select(func.count()).select_from(AgentRunStateOrm).where(
                AgentRunStateOrm.status.in_(
                    AGENT_RUN_LEGACY_CLAIMABLE_STATUSES
                    + AGENT_RUN_UNIFIED_CLAIMABLE_STATUSES
                )
            )
        )
        or 0
    )
    failed_logs = int(
        await db.scalar(
            select(func.count()).select_from(SystemLog).where(
                SystemLog.level.in_({"error", "critical"}),
                SystemLog.created_at >= since,
            )
        )
        or 0
    )
    graph_task_types = {"graph_sync", "graph_rebuild"}
    pending_graph_tasks = int(
        await db.scalar(
            select(func.count()).select_from(KnowledgeTaskOrm).where(
                KnowledgeTaskOrm.task_type.in_(graph_task_types),
                KnowledgeTaskOrm.status.in_({"queued", "running"}),
            )
        )
        or 0
    )
    failed_graph_tasks_24h = int(
        await db.scalar(
            select(func.count()).select_from(KnowledgeTaskOrm).where(
                KnowledgeTaskOrm.task_type.in_(graph_task_types),
                KnowledgeTaskOrm.status == "failed",
                func.coalesce(
                    KnowledgeTaskOrm.finished_at,
                    KnowledgeTaskOrm.updated_at,
                    KnowledgeTaskOrm.created_at,
                )
                >= since,
            )
        )
        or 0
    )
    pending_graph_profile_repairs = int(
        await db.scalar(
            select(func.count())
            .select_from(KnowledgeGraphRevisionOrm)
            .where(
                or_(
                    KnowledgeGraphRevisionOrm.stats_json[
                        "profile_repair_pending"
                    ].as_boolean().is_(True),
                    KnowledgeGraphRevisionOrm.stats_json[
                        "profile_delete_pending"
                    ].as_boolean().is_(True),
                )
            )
        )
        or 0
    )
    return (
        pending,
        failed_logs,
        pending_graph_tasks,
        failed_graph_tasks_24h,
        pending_graph_profile_repairs,
    )


async def daily_run_count(db: AsyncSession, workspace_id: str, since: datetime) -> int:
    """
    Count agent runs created within a workspace from the specified time onward.
    
    Parameters:
        workspace_id (str): Identifier of the workspace.
        since (datetime): Start of the counting period.
    
    Returns:
        int: Number of matching agent runs.
    """
    return int(
        await db.scalar(
            select(func.count()).select_from(AgentRunOrm).where(
                AgentRunOrm.workspace_id == workspace_id,
                AgentRunOrm.created_at >= since,
            )
        )
        or 0
    )
