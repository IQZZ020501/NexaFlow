from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.api.deps import get_current_user, get_settings
from nexaflow.core.config import Settings
from nexaflow.db.session import get_db
from nexaflow.models.user import User
from nexaflow.schemas.user import (
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    TokenResponse,
)
from nexaflow.services.auth import authenticate_user, change_password, get_me

router = APIRouter(prefix="/auth", tags=["auth"])


def get_request_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    ip_address = forwarded_for.split(",", 1)[0].strip()
    if ip_address:
        return ip_address
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    return await authenticate_user(
        db,
        payload.username,
        payload.password,
        settings,
        ip_address=get_request_ip(request),
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_current_password(
    payload: ChangePasswordRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await change_password(db, user, payload.new_password, payload.current_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MeResponse:
    return await get_me(db, user)
