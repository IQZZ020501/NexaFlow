from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit.models import (
    AUDIT_RETENTION_SETTINGS_ID,
    AuditLog,
    AuditRetentionSettings,
)
from app.entities.audit import (
    AuditLog as AuditLogEntity,
    AuditRetentionSettings as AuditRetentionSettingsEntity,
)
from app.entities.defaults import utc_now
from app.infra.db.mapping import to_entity


def add(db: AsyncSession, entity: AuditLogEntity) -> None:
    """Stage an audit log row; the caller coordinates the commit."""
    db.add(
        AuditLog(
            id=entity.id,
            actor_user_id=entity.actor_user_id,
            actor_username=entity.actor_username,
            actor_name=entity.actor_name,
            workspace_id=entity.workspace_id,
            action=entity.action,
            resource_type=entity.resource_type,
            resource_id=entity.resource_id,
            resource_name=entity.resource_name,
            details=entity.details,
        )
    )



def _audit_filter_clauses(
    *,
    workspace_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    search: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list:
    clauses = []
    if workspace_id:
        clauses.append(AuditLog.workspace_id == workspace_id)
    if actor:
        clauses.append(
            or_(
                AuditLog.actor_user_id == actor,
                AuditLog.actor_username.ilike(f"%{actor}%"),
                AuditLog.actor_name.ilike(f"%{actor}%"),
            )
        )
    if action:
        clauses.append(AuditLog.action == action)
    if resource_type:
        clauses.append(AuditLog.resource_type == resource_type)
    if resource_id:
        clauses.append(AuditLog.resource_id == resource_id)
    if search:
        pattern = f"%{search}%"
        clauses.append(
            or_(
                AuditLog.action.ilike(pattern),
                AuditLog.resource_name.ilike(pattern),
                AuditLog.resource_type.ilike(pattern),
                AuditLog.actor_username.ilike(pattern),
            )
        )
    if from_date:
        clauses.append(AuditLog.created_at >= from_date)
    if to_date:
        clauses.append(AuditLog.created_at < to_date)
    return clauses


async def list_audit_logs(
    db: AsyncSession,
    limit: int,
    offset: int = 0,
    *,
    workspace_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    search: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[AuditLogEntity]:
    """
    Retrieve audit logs with optional filters and pagination.
    
    Parameters:
        limit (int): Maximum number of logs to retrieve.
        offset (int): Number of logs to skip.
        workspace_id (str | None): Workspace identifier used to filter logs.
        actor (str | None): User ID, username, or name used to filter logs.
        action (str | None): Action used to filter logs.
        resource_type (str | None): Resource type used to filter logs.
        resource_id (str | None): Resource identifier used to filter logs.
        search (str | None): Text matched against action, resource name or type, and actor username.
        from_date (datetime | None): Inclusive lower bound for the creation date.
        to_date (datetime | None): Exclusive upper bound for the creation date.
    
    Returns:
        list[AuditLogEntity]: Matching audit logs ordered from newest to oldest.
    """
    statement = select(AuditLog).where(
        *_audit_filter_clauses(
            workspace_id=workspace_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            search=search,
            from_date=from_date,
            to_date=to_date,
        )
    )

    result = await db.scalars(
        statement
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(AuditLogEntity, row) for row in result.all()]


async def count_audit_logs(
    db: AsyncSession,
    *,
    workspace_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    search: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> int:
    statement = select(func.count()).select_from(AuditLog).where(
        *_audit_filter_clauses(
            workspace_id=workspace_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            search=search,
            from_date=from_date,
            to_date=to_date,
        )
    )
    return int(await db.scalar(statement) or 0)


async def list_workspace_audit_logs(
    db: AsyncSession,
    workspace_id: str,
    limit: int,
    offset: int = 0,
    *,
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    search: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[AuditLogEntity]:
    """
    Retrieve audit logs for a workspace with optional filtering and pagination.
    
    Parameters:
        workspace_id (str): Identifier of the workspace whose audit logs are retrieved.
        actor (str | None): Optional actor identity or name filter.
        action (str | None): Optional action filter.
        resource_type (str | None): Optional resource type filter.
        resource_id (str | None): Optional resource identifier filter.
        search (str | None): Optional text search across audit log fields.
        from_date (datetime | None): Optional inclusive lower bound for creation time.
        to_date (datetime | None): Optional exclusive upper bound for creation time.
    
    Returns:
        list[AuditLogEntity]: Audit logs matching the filters, ordered newest first.
    """
    return await list_audit_logs(
        db,
        limit,
        offset,
        workspace_id=workspace_id,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        from_date=from_date,
        to_date=to_date,
    )


async def get_retention_settings(db: AsyncSession) -> AuditRetentionSettingsEntity | None:
    """Return the singleton global audit retention settings row if configured."""
    row = await db.scalar(
        select(AuditRetentionSettings).where(
            AuditRetentionSettings.id == AUDIT_RETENTION_SETTINGS_ID
        )
    )
    return to_entity(AuditRetentionSettingsEntity, row) if row is not None else None


async def save_retention_settings(
    db: AsyncSession,
    *,
    retention_days: int | None,
    updated_by_user_id: str | None,
) -> AuditRetentionSettingsEntity:
    """Create or update the singleton audit retention settings row; caller commits."""
    now = utc_now()
    row = await db.scalar(
        select(AuditRetentionSettings).where(
            AuditRetentionSettings.id == AUDIT_RETENTION_SETTINGS_ID
        )
    )
    if row is None:
        row = AuditRetentionSettings(
            id=AUDIT_RETENTION_SETTINGS_ID,
            retention_days=retention_days,
            updated_by_user_id=updated_by_user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.retention_days = retention_days
        row.updated_by_user_id = updated_by_user_id
        row.updated_at = now
    await db.flush()
    return to_entity(AuditRetentionSettingsEntity, row)


async def delete_audit_logs_before(
    db: AsyncSession,
    cutoff: datetime,
    *,
    batch_size: int = 1000,
) -> int:
    """Delete up to ``batch_size`` audit logs strictly older than ``cutoff``."""
    ids = list(
        (
            await db.scalars(
                select(AuditLog.id)
                .where(AuditLog.created_at < cutoff)
                .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
                .limit(batch_size)
            )
        ).all()
    )
    if not ids:
        return 0
    result = await db.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))
    return int(result.rowcount or len(ids))
