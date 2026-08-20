from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.llm.models import RegisteredModel
from app.domain.team import Team as TeamOrm
from app.domain.user import User as UserOrm
from app.domain.workspace import WorkspaceMembership as WorkspaceMembershipOrm
from app.infrastructure.system_log import SystemLog
from app.shareddomain.agents.models import Agent as AgentOrm
from app.shareddomain.agents.models import AgentRun as AgentRunOrm
from app.shareddomain.knowledge.models import KnowledgeBase as KnowledgeBaseOrm
from app.shareddomain.knowledge.models import KnowledgeTask as KnowledgeTaskOrm
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
    active_statuses = {
        "queued", "planning", "planned", "running", "awaiting_approval",
        "awaiting_input", "awaiting_child", "queued_v2", "running_v2",
        "awaiting_approval_v2", "awaiting_input_v2", "awaiting_child_v2",
    }
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
        "active_runs": await _count(db, AgentRunOrm, workspace_id, AgentRunOrm.status.in_(active_statuses)),
        "failed_runs_24h": await _count(
            db, AgentRunOrm, workspace_id,
            AgentRunOrm.status == "failed", AgentRunOrm.created_at >= day_ago,
        ),
        "failed_tasks_24h": await _count(
            db, KnowledgeTaskOrm, workspace_id,
            KnowledgeTaskOrm.status == "failed", KnowledgeTaskOrm.created_at >= day_ago,
        ),
    }


async def health_counts(db: AsyncSession, since: datetime) -> tuple[int, int]:
    """
    Count pending knowledge tasks and agent runs, along with recent error and critical system logs.
    
    Parameters:
        since (datetime): Start time for counting system logs.
    
    Returns:
        tuple[int, int]: The number of pending tasks and runs, followed by the number of error or critical logs created since ``since``.
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
            select(func.count()).select_from(AgentRunOrm).where(
                AgentRunOrm.status.in_({"queued", "queued_v2", "running", "running_v2"})
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
    return pending, failed_logs


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
