from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.audit.schemas import AuditLogResponse
from nexaflow.audit.services import list_audit_logs
from nexaflow.db.session import get_db
from nexaflow.identity.dependencies import require_global_admin
from nexaflow.identity.models import User

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=list[AuditLogResponse])
async def list_logs(
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AuditLogResponse]:
    return await list_audit_logs(db, limit)
