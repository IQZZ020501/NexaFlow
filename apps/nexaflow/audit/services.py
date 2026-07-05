from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.audit.models import AuditLog
from nexaflow.audit.schemas import AuditLogResponse
from nexaflow.identity.models import User


def record_audit_log(
    db: AsyncSession,
    actor: User,
    action: str,
    resource_type: str,
    resource_id: str,
    resource_name: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            actor_username=actor.username,
            actor_name=actor.name,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            details=details or {},
        )
    )


def audit_log_to_response(log: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=log.id,
        actor_user_id=log.actor_user_id,
        actor_username=log.actor_username,
        actor_name=log.actor_name,
        action=log.action,
        resource_type=log.resource_type,
        resource_id=log.resource_id,
        resource_name=log.resource_name,
        details=log.details,
        created_at=log.created_at,
    )


async def list_audit_logs(db: AsyncSession, limit: int) -> list[AuditLogResponse]:
    result = await db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    return [audit_log_to_response(item) for item in result.all()]
