from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.workspace_governance import WorkspaceGovernance as WorkspaceGovernanceOrm
from app.entities.workspace_governance import WorkspaceGovernance
from app.infrastructure.repositories import mapping


async def get(db: AsyncSession, workspace_id: str) -> WorkspaceGovernance | None:
    row = await db.get(WorkspaceGovernanceOrm, workspace_id)
    return mapping.to_entity(WorkspaceGovernance, row) if row is not None else None


async def save(
    db: AsyncSession,
    entity: WorkspaceGovernance,
) -> WorkspaceGovernance:
    row = await db.get(WorkspaceGovernanceOrm, entity.workspace_id)
    if row is None:
        row = WorkspaceGovernanceOrm(
            workspace_id=entity.workspace_id,
            daily_run_limit=entity.daily_run_limit,
            monthly_token_limit=entity.monthly_token_limit,
            alert_threshold_percent=entity.alert_threshold_percent,
            retention_days=entity.retention_days,
            timezone=entity.timezone,
            updated_by_user_id=entity.updated_by_user_id,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
        db.add(row)
    else:
        for field in (
            "daily_run_limit",
            "monthly_token_limit",
            "alert_threshold_percent",
            "retention_days",
            "timezone",
            "updated_by_user_id",
            "updated_at",
        ):
            setattr(row, field, getattr(entity, field))
    await db.flush()
    return mapping.to_entity(WorkspaceGovernance, row)
