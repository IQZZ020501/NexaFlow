from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.audit.models import AuditLog


async def list_audit_logs(db: AsyncSession, limit: int) -> list[AuditLog]:
    result = await db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    return list(result.all())


async def list_workspace_audit_logs(
    db: AsyncSession,
    workspace_id: str,
    limit: int,
) -> list[AuditLog]:
    result = await db.scalars(
        select(AuditLog)
        .where(AuditLog.workspace_id == workspace_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    return list(result.all())
