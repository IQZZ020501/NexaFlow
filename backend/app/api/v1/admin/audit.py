from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.audit import list_audit_logs
from app.schemas.audit import AuditLogResponse
from app.infrastructure.session import get_db
from app.api.deps import require_global_admin
from app.entities.user import User

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=list[AuditLogResponse])
async def list_logs(
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
    actor: Annotated[str | None, Query(max_length=120)] = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    resource_type: Annotated[str | None, Query(max_length=40)] = None,
    resource_id: Annotated[str | None, Query(max_length=36)] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    from_date: Annotated[datetime | None, Query(alias="from")] = None,
    to_date: Annotated[datetime | None, Query(alias="to")] = None,
) -> list[AuditLogResponse]:
    """
    List audit logs with pagination and optional filtering criteria.
    
    Parameters:
        limit (int): Maximum number of logs to return.
        offset (int): Number of logs to skip.
        workspace_id (str | None): Filter by workspace identifier.
        actor (str | None): Filter by actor.
        action (str | None): Filter by action.
        resource_type (str | None): Filter by resource type.
        resource_id (str | None): Filter by resource identifier.
        search (str | None): Filter by matching search text.
        from_date (datetime | None): Include logs from this date and time onward.
        to_date (datetime | None): Include logs up to this date and time.
    
    Returns:
        list[AuditLogResponse]: The matching audit log records.
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
