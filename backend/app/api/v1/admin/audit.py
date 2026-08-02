from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.audit import AuditLogResponse
from app.shareddomain.audit.services import list_audit_logs
from app.infrastructure.session import get_db
from app.api.deps import require_global_admin
from app.domain.user import User

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=list[AuditLogResponse])
async def list_logs(
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AuditLogResponse]:
    return await list_audit_logs(db, limit)
