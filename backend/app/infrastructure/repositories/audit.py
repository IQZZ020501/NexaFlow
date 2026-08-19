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
