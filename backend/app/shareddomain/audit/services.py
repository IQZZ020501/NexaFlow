from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.audit import AuditLog
from app.entities.user import User
from app.infrastructure.repositories import audit as audit_repository
from app.schemas.audit import AuditLogResponse


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
        to_date (datetime | None): Includes logs created on or before this date.
    
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
        to_date (datetime | None): Include logs created on or before this date.
    
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
