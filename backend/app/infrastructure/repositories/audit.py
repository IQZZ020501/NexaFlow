from sqlalchemy import select
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
) -> list[AuditLogEntity]:
    result = await db.scalars(
        select(AuditLog)
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
) -> list[AuditLogEntity]:
    result = await db.scalars(
        select(AuditLog)
        .where(AuditLog.workspace_id == workspace_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(AuditLogEntity, row) for row in result.all()]
