from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.user import User
from app.entities.workspace import Workspace
from app.entities.workspace_governance import WorkspaceGovernance
from app.domain.workspace_governance import WorkspaceGovernance as WorkspaceGovernanceOrm  # noqa: F401
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import governance as governance_repository
from app.infrastructure.repositories import workspace_governance as workspace_governance_repository
from app.schemas.governance import (
    AdminHealthResponse,
    HealthComponent,
    WorkspaceGovernanceResponse,
    WorkspaceGovernanceUpdateRequest,
    WorkspaceInventoryResponse,
)
from app.shareddomain.audit.services import record_audit_log


def _governance_response(entity: WorkspaceGovernance) -> WorkspaceGovernanceResponse:
    return WorkspaceGovernanceResponse(
        workspace_id=entity.workspace_id,
        daily_run_limit=entity.daily_run_limit,
        monthly_token_limit=entity.monthly_token_limit,
        alert_threshold_percent=entity.alert_threshold_percent,
        retention_days=entity.retention_days,
        timezone=entity.timezone,
        updated_at=entity.updated_at,
    )


async def get_workspace_governance(
    db: AsyncSession,
    workspace_id: str,
) -> WorkspaceGovernanceResponse:
    entity = await workspace_governance_repository.get(db, workspace_id)
    return _governance_response(entity or WorkspaceGovernance(workspace_id=workspace_id))


async def update_workspace_governance(
    db: AsyncSession,
    workspace: Workspace,
    actor: User,
    payload: WorkspaceGovernanceUpdateRequest,
) -> WorkspaceGovernanceResponse:
    entity = await workspace_governance_repository.get(db, workspace.id)
    if entity is None:
        entity = WorkspaceGovernance(workspace_id=workspace.id)
    for key, value in payload.model_dump().items():
        setattr(entity, key, value)
    entity.updated_by_user_id = actor.id
    await workspace_governance_repository.save(db, entity)
    record_audit_log(
        db,
        actor,
        "workspace.governance.update",
        "workspace",
        workspace.id,
        workspace.name,
        payload.model_dump(),
        workspace_id=workspace.id,
    )
    await db.commit()
    return _governance_response(entity)


async def get_workspace_inventory(
    db: AsyncSession,
    workspace_id: str,
) -> WorkspaceInventoryResponse:
    now = utc_now()
    day_ago = now - timedelta(days=1)
    counts = await governance_repository.workspace_inventory_counts(db, workspace_id, day_ago)
    return WorkspaceInventoryResponse(
        workspace_id=workspace_id,
        **counts,
        updated_at=now,
    )


async def get_admin_health(
    db: AsyncSession,
    settings: Settings,
) -> AdminHealthResponse:
    checked_at = utc_now()
    components: dict[str, HealthComponent] = {}
    try:
        await db.execute(text("SELECT 1"))
        components["database"] = HealthComponent(status="ok")
    except Exception:
        components["database"] = HealthComponent(status="error", detail="unavailable")
    configured = {
        "redis": bool(settings.celery_broker_url),
        "qdrant": bool(settings.qdrant_url),
        "storage": bool(settings.knowledge_storage_dir),
        "worker": bool(settings.celery_broker_url),
    }
    for name, is_configured in configured.items():
        components[name] = HealthComponent(
            status="configured" if is_configured else "not_configured"
        )
    pending_tasks, failed_logs_24h = await governance_repository.health_counts(
        db, checked_at - timedelta(days=1)
    )
    healthy = all(item.status in {"ok", "configured"} for item in components.values())
    return AdminHealthResponse(
        status="ok" if healthy else "degraded",
        components=components,
        pending_tasks=pending_tasks,
        failed_logs_24h=failed_logs_24h,
        checked_at=checked_at,
    )


async def enforce_workspace_run_quota(
    db: AsyncSession,
    workspace_id: str,
) -> None:
    governance = await workspace_governance_repository.get(db, workspace_id)
    if governance is None or governance.daily_run_limit is None:
        return
    today = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = await governance_repository.daily_run_count(db, workspace_id, today)
    if used >= governance.daily_run_limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Workspace daily run quota exceeded.")
