from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit.models import (
    AUDIT_RETENTION_SETTINGS_ID,
    MAX_AUDIT_RETENTION_DAYS,
    MIN_AUDIT_RETENTION_DAYS,
)
from app.entities.audit import AuditLog
from app.entities.defaults import utc_now
from app.entities.identity.user import User
from app.infra.db.repositories.audit import repository as audit_repository
from app.infra.db.session import get_session_factory
from app.schemas.audit import AuditLogResponse, AuditRetentionPolicyResponse


def record_audit_log(
    db: AsyncSession,
    actor: User,
    action: str,
    resource_type: str,
    resource_id: str,
    resource_name: str,
    details: dict[str, Any] | None = None,
    workspace_id: str | None = None,
) -> None:
    audit_repository.add(
        db,
        AuditLog(
            actor_user_id=actor.id,
            actor_username=actor.username,
            actor_name=actor.name,
            workspace_id=workspace_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            details=details or {},
        ),
    )


def audit_log_to_response(log: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=log.id,
        actor_user_id=log.actor_user_id,
        actor_username=log.actor_username,
        actor_name=log.actor_name,
        workspace_id=log.workspace_id,
        action=log.action,
        resource_type=log.resource_type,
        resource_id=log.resource_id,
        resource_name=log.resource_name,
        details=log.details,
        created_at=log.created_at,
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
) -> list[AuditLogResponse]:
    """
    Retrieve audit logs with pagination and optional filtering criteria.
    
    Parameters:
        workspace_id (str | None): Restricts results to a workspace.
        actor (str | None): Restricts results to the specified actor.
        action (str | None): Restricts results to the specified action.
        resource_type (str | None): Restricts results to the specified resource type.
        resource_id (str | None): Restricts results to the specified resource.
        search (str | None): Filters results by text search.
        from_date (datetime | None): Includes logs created on or after this date.
        to_date (datetime | None): Excludes logs created on or after this date.
    
    Returns:
        list[AuditLogResponse]: The matching audit logs as response objects.
    """
    logs = await audit_repository.list_audit_logs(
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
    return [audit_log_to_response(item) for item in logs]


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
) -> list[AuditLogResponse]:
    """
    Retrieve audit logs for a workspace with optional filtering and pagination.
    
    Parameters:
        workspace_id (str): Identifier of the workspace whose logs are retrieved.
        limit (int): Maximum number of logs to return.
        offset (int): Number of logs to skip before collecting results.
        actor (str | None): Filter by the acting user.
        action (str | None): Filter by action type.
        resource_type (str | None): Filter by resource type.
        resource_id (str | None): Filter by resource identifier.
        search (str | None): Search log content.
        from_date (datetime | None): Include logs created on or after this date.
        to_date (datetime | None): Exclude logs created on or after this date.
    
    Returns:
        list[AuditLogResponse]: Audit log responses matching the workspace and filters.
    """
    logs = await audit_repository.list_workspace_audit_logs(
        db,
        workspace_id,
        limit,
        offset,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        from_date=from_date,
        to_date=to_date,
    )
    return [audit_log_to_response(item) for item in logs]


async def count_audit_logs(db: AsyncSession, **filters: Any) -> int:
    return await audit_repository.count_audit_logs(db, **filters)


async def get_audit_retention_policy(
    db: AsyncSession,
) -> AuditRetentionPolicyResponse:
    """Return the global audit log retention policy (defaulting to keep-all)."""
    settings = await audit_repository.get_retention_settings(db)
    if settings is None:
        return AuditRetentionPolicyResponse(retention_days=None, updated_at=None)
    return AuditRetentionPolicyResponse(
        retention_days=settings.retention_days,
        updated_at=settings.updated_at,
    )


async def update_audit_retention_policy(
    db: AsyncSession,
    actor: User,
    retention_days: int | None,
) -> AuditRetentionPolicyResponse:
    """Persist the global audit retention policy and emit an audit trail entry."""
    if retention_days is not None and not (
        MIN_AUDIT_RETENTION_DAYS <= retention_days <= MAX_AUDIT_RETENTION_DAYS
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Retention days must be between {MIN_AUDIT_RETENTION_DAYS} "
                f"and {MAX_AUDIT_RETENTION_DAYS}."
            ),
        )

    existing = await audit_repository.get_retention_settings(db)
    previous_retention_days = existing.retention_days if existing is not None else None
    saved = await audit_repository.save_retention_settings(
        db,
        retention_days=retention_days,
        updated_by_user_id=actor.id,
    )
    record_audit_log(
        db,
        actor=actor,
        action="audit.retention.update",
        resource_type="audit_retention",
        resource_id=AUDIT_RETENTION_SETTINGS_ID,
        resource_name="Audit Log Retention",
        details={
            "previous_retention_days": previous_retention_days,
            "retention_days": retention_days,
        },
    )
    await db.commit()
    return AuditRetentionPolicyResponse(
        retention_days=saved.retention_days,
        updated_at=saved.updated_at,
    )


async def cleanup_expired_audit_logs(
    db: AsyncSession | None = None,
    *,
    batch_size: int = 1000,
    max_batches: int = 20,
) -> int:
    """Delete audit logs older than the configured retention period in bounded batches."""

    async def _run(session: AsyncSession) -> int:
        settings = await audit_repository.get_retention_settings(session)
        if settings is None or settings.retention_days is None:
            return 0
        cutoff = utc_now() - timedelta(days=settings.retention_days)
        total_deleted = 0
        for _ in range(max_batches):
            deleted = await audit_repository.delete_audit_logs_before(
                session,
                cutoff,
                batch_size=batch_size,
            )
            if deleted <= 0:
                break
            await session.commit()
            total_deleted += deleted
            if deleted < batch_size:
                break
        return total_deleted

    if db is not None:
        return await _run(db)

    async with get_session_factory()() as owned_db:
        return await _run(owned_db)
