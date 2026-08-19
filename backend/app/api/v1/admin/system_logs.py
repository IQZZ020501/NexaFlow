from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_global_admin
from app.application.system_logs import list_system_logs
from app.entities.user import User
from app.infrastructure.session import get_db
from app.schemas.system_log import SystemLogResponse

router = APIRouter(prefix="/system-logs", tags=["system-logs"])


@router.get("", response_model=list[SystemLogResponse])
async def list_logs(
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    level: Annotated[str | None, Query(max_length=20)] = None,
    event: Annotated[str | None, Query(max_length=80)] = None,
    status_code: Annotated[int | None, Query(ge=100, le=599)] = None,
    user_id: Annotated[str | None, Query(max_length=36)] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    from_date: Annotated[datetime | None, Query(alias="from")] = None,
    to_date: Annotated[datetime | None, Query(alias="to")] = None,
    include_stack: Annotated[bool, Query()] = False,
) -> list[SystemLogResponse]:
    return await list_system_logs(
        db,
        limit,
        offset,
        level=level,
        event=event,
        status_code=status_code,
        user_id=user_id,
        search=search,
        from_date=from_date,
        to_date=to_date,
        include_stack=include_stack,
    )
