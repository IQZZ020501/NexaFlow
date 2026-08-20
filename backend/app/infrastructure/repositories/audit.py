from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.audit import AuditLog as AuditLogEntity
from app.infrastructure.repositories.mapping import to_entity
from app.shareddomain.audit.models import AuditLog


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
    statement = select(AuditLog)
    if workspace_id:
        statement = statement.where(AuditLog.workspace_id == workspace_id)
    if actor:
        statement = statement.where(
            or_(
                AuditLog.actor_user_id == actor,
                AuditLog.actor_username.ilike(f"%{actor}%"),
                AuditLog.actor_name.ilike(f"%{actor}%"),
            )
        )
    if action:
        statement = statement.where(AuditLog.action == action)
    if resource_type:
        statement = statement.where(AuditLog.resource_type == resource_type)
    if resource_id:
        statement = statement.where(AuditLog.resource_id == resource_id)
    if search:
        statement = statement.where(
            or_(
                AuditLog.action.ilike(f"%{search}%"),
                AuditLog.resource_name.ilike(f"%{search}%"),
                AuditLog.resource_type.ilike(f"%{search}%"),
                AuditLog.actor_username.ilike(f"%{search}%"),
            )
        )
    if from_date:
        statement = statement.where(AuditLog.created_at >= from_date)
    if to_date:
        statement = statement.where(AuditLog.created_at < to_date)
    result = await db.scalars(
        statement
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(AuditLogEntity, row) for row in result.all()]


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
