from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_settings
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.entities.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    TokenResponse,
    RefreshSessionResponse,
    UserResponse,
)
from app.application.identity import (
    authenticate_user,
    change_password,
    get_me,
    refresh_access_token,
    revoke_refresh_token,
)
from app.application.sessions import (
    list_user_sessions,
    revoke_other_user_sessions,
    revoke_user_session,
)
from app.application.invitations import accept_workspace_invitation
from app.schemas.invitation import WorkspaceInvitationAcceptRequest

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_TOKEN_COOKIE = "nexaflow_refresh_token"
REFRESH_TOKEN_COOKIE_PATH = "/api/v1/auth"


@router.post("/invitations/accept", response_model=UserResponse)
async def accept_invitation(
    payload: WorkspaceInvitationAcceptRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    return await accept_workspace_invitation(db, payload)


def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        token,
        max_age=settings.refresh_token_expires_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path=REFRESH_TOKEN_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_TOKEN_COOKIE,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path=REFRESH_TOKEN_COOKIE_PATH,
    )


def get_request_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    token_response, refresh_token = await authenticate_user(
        db,
        payload.username,
        payload.password,
        settings,
        ip_address=get_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    set_refresh_cookie(response, refresh_token, settings)
    return token_response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE)] = None,
) -> TokenResponse:
    if refresh_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token required.")
    return await refresh_access_token(db, refresh_token, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE)] = None,
) -> Response:
    await revoke_refresh_token(db, refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, settings)
    return response


@router.get("/sessions", response_model=list[RefreshSessionResponse])
async def list_sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE)] = None,
) -> list[RefreshSessionResponse]:
    return await list_user_sessions(db, user, refresh_token)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await revoke_user_session(db, user.id, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_other_sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE)] = None,
) -> Response:
    await revoke_other_user_sessions(db, user, refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_current_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    refresh_token = await change_password(
        db,
        user,
        payload.new_password,
        settings,
        payload.current_password,
        ip_address=get_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_refresh_cookie(response, refresh_token, settings)
    return response


@router.get("/me", response_model=MeResponse)
async def me(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MeResponse:
    return await get_me(db, user)
