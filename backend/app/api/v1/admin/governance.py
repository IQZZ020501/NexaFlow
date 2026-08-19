from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_settings, require_global_admin
from app.application.governance import get_admin_health
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.schemas.governance import AdminHealthResponse

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/health", response_model=AdminHealthResponse)
async def health(
    _: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminHealthResponse:
    return await get_admin_health(db, settings)
