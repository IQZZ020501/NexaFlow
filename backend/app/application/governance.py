import asyncio
import tempfile
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException, status
from redis.asyncio import Redis
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
from app.ports.vector_store import check_vector_store_health
from app.schemas.governance import (
    AdminHealthResponse,
    HealthComponent,
    WorkspaceGovernanceResponse,
    WorkspaceGovernanceUpdateRequest,
    WorkspaceInventoryResponse,
)
from app.shareddomain.audit.services import record_audit_log


HEALTH_PROBE_TIMEOUT_SECONDS = 3.0
_STORAGE_PROBE_CONTENT = b"nexaflow-health"


async def _check_health_component(
    configured: bool,
    probe: Callable[[], Awaitable[None]],
) -> HealthComponent:
    if not configured:
        return HealthComponent(status="not_configured")
    try:
        async with asyncio.timeout(HEALTH_PROBE_TIMEOUT_SECONDS):
            await probe()
    except TimeoutError:
        return HealthComponent(
            status="error",
            detail="timeout",
        )
    except Exception:
        return HealthComponent(
            status="error",
            detail="unavailable",
        )
    return HealthComponent(status="ok")


async def _probe_database(db: AsyncSession) -> None:
    await db.execute(text("SELECT 1"))


async def _probe_redis(settings: Settings) -> None:
    client = Redis.from_url(
        settings.celery_broker_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        if not await client.ping():
            raise RuntimeError("Redis did not acknowledge the health probe.")
    finally:
        await client.aclose()


async def _probe_qdrant(settings: Settings) -> None:
    await asyncio.to_thread(check_vector_store_health, settings)


def _probe_storage_sync(root: Path) -> None:
    if not root.is_dir():
        raise OSError("Storage directory is unavailable.")
    probe_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".nexaflow-health-",
            dir=root,
            delete=False,
        ) as probe:
            probe.write(_STORAGE_PROBE_CONTENT)
            probe_path = Path(probe.name)
        if probe_path.read_bytes() != _STORAGE_PROBE_CONTENT:
            raise OSError("Storage probe content could not be read back.")
    finally:
        if probe_path is not None:
            probe_path.unlink(missing_ok=True)


async def _probe_storage(settings: Settings) -> None:
    if settings.knowledge_storage_dir is None:
        raise OSError("Storage directory is not configured.")
    await asyncio.to_thread(_probe_storage_sync, settings.knowledge_storage_dir)


def _probe_worker_sync(settings: Settings) -> None:
    from app.infrastructure.celery import celery_app

    with celery_app.connection_for_read(
        settings.celery_broker_url,
        connect_timeout=2,
    ) as connection:
        replies = celery_app.control.ping(
            timeout=2,
            limit=1,
            connection=connection,
        )
    if not replies:
        raise RuntimeError("No Celery worker replied to the health probe.")


async def _probe_worker(settings: Settings) -> None:
    await asyncio.to_thread(_probe_worker_sync, settings)


def _governance_response(entity: WorkspaceGovernance) -> WorkspaceGovernanceResponse:
    """Convert workspace governance settings into their response representation.
    
    Parameters:
    	entity (WorkspaceGovernance): Governance settings to convert.
    
    Returns:
    	WorkspaceGovernanceResponse: The workspace governance response.
    """
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
    """
    Retrieve governance settings for a workspace.
    
    Parameters:
    	workspace_id (str): Identifier of the workspace whose governance settings to retrieve.
    
    Returns:
    	WorkspaceGovernanceResponse: The workspace governance settings, including defaults when no persisted settings exist.
    """
    entity = await workspace_governance_repository.get(db, workspace_id)
    return _governance_response(entity or WorkspaceGovernance(workspace_id=workspace_id))


async def update_workspace_governance(
    db: AsyncSession,
    workspace: Workspace,
    actor: User,
    payload: WorkspaceGovernanceUpdateRequest,
) -> WorkspaceGovernanceResponse:
    """
    Apply governance settings to a workspace and record the update.
    
    Parameters:
        workspace (Workspace): Workspace whose governance settings are updated.
        actor (User): User responsible for the update.
        payload (WorkspaceGovernanceUpdateRequest): Governance values to apply.
    
    Returns:
        WorkspaceGovernanceResponse: The updated workspace governance settings.
    """
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
    """
    Retrieve workspace inventory counts for the previous 24 hours.
    
    Parameters:
    	workspace_id (str): Identifier of the workspace whose inventory is retrieved.
    
    Returns:
    	WorkspaceInventoryResponse: Inventory counts for the workspace, including the current timestamp.
    """
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
    """
    Assess system health and summarize component status and recent operational counts.
    
    Parameters:
    	db (AsyncSession): Database session used to check connectivity and retrieve health counts.
    	settings (Settings): Application configuration used to assess infrastructure readiness.
    
    Returns:
    	AdminHealthResponse: Health status, component details, pending task count, failed log count from the previous 24 hours, and check timestamp.
    """
    checked_at = utc_now()
    names = ("database", "redis", "qdrant", "storage", "worker")
    results = await asyncio.gather(
        _check_health_component(True, lambda: _probe_database(db)),
        _check_health_component(
            bool(settings.celery_broker_url),
            lambda: _probe_redis(settings),
        ),
        _check_health_component(
            bool(settings.qdrant_url),
            lambda: _probe_qdrant(settings),
        ),
        _check_health_component(
            settings.knowledge_storage_dir is not None,
            lambda: _probe_storage(settings),
        ),
        _check_health_component(
            bool(settings.celery_broker_url),
            lambda: _probe_worker(settings),
        ),
    )
    components = dict(zip(names, results, strict=True))

    pending_tasks = 0
    failed_logs_24h = 0
    pending_graph_tasks = 0
    failed_graph_tasks_24h = 0
    pending_graph_profile_repairs = 0
    if components["database"].status == "ok":
        try:
            async with asyncio.timeout(HEALTH_PROBE_TIMEOUT_SECONDS):
                (
                    pending_tasks,
                    failed_logs_24h,
                    pending_graph_tasks,
                    failed_graph_tasks_24h,
                    pending_graph_profile_repairs,
                ) = (
                    await governance_repository.health_counts(
                        db,
                        checked_at - timedelta(days=1),
                    )
                )
        except TimeoutError:
            components["database"] = HealthComponent(
                status="error",
                detail="timeout",
            )
        except Exception:
            components["database"] = HealthComponent(
                status="error",
                detail="unavailable",
            )

    healthy = all(item.status == "ok" for item in components.values())
    return AdminHealthResponse(
        status="ok" if healthy else "degraded",
        components=components,
        pending_tasks=pending_tasks,
        failed_logs_24h=failed_logs_24h,
        pending_graph_tasks=pending_graph_tasks,
        failed_graph_tasks_24h=failed_graph_tasks_24h,
        pending_graph_profile_repairs=pending_graph_profile_repairs,
        checked_at=checked_at,
    )


async def enforce_workspace_run_quota(
    db: AsyncSession,
    workspace_id: str,
) -> None:
    """
    Enforce the workspace's configured daily run quota.
    
    Parameters:
    	db (AsyncSession): Database session used to retrieve governance settings and run usage.
    	workspace_id (str): Identifier of the workspace whose quota should be enforced.
    
    Raises:
    	HTTPException: If the workspace has reached or exceeded its configured daily run limit.
    """
    governance = await workspace_governance_repository.get(db, workspace_id)
    if governance is None or governance.daily_run_limit is None:
        return
    today = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = await governance_repository.daily_run_count(db, workspace_id, today)
    if used >= governance.daily_run_limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Workspace daily run quota exceeded.")
