from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Settings, User, get_db, get_settings, require_global_admin
from app.application.smtp import (
    get_smtp_settings,
    test_smtp_settings,
    update_smtp_settings,
)
from app.schemas.smtp import SmtpSettingsResponse, SmtpSettingsUpdateRequest, SmtpTestRequest


router = APIRouter(prefix="/smtp", tags=["smtp"])


@router.get("", response_model=SmtpSettingsResponse)
async def read_smtp_settings(
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SmtpSettingsResponse:
    return await get_smtp_settings(db)


@router.patch("", response_model=SmtpSettingsResponse)
async def patch_smtp_settings(
    payload: SmtpSettingsUpdateRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SmtpSettingsResponse:
    return await update_smtp_settings(db, actor, payload, settings)


@router.post("/test", response_model=dict[str, bool])
async def send_smtp_test(
    payload: SmtpTestRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    return await test_smtp_settings(db, actor, payload, settings)
