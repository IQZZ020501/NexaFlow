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
    PasswordResetConfirmRequest,
    PasswordResetRequest,
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
from app.application.password_reset import (
    confirm_password_reset,
    request_password_reset,
)
from app.schemas.invitation import WorkspaceInvitationAcceptRequest

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_TOKEN_COOKIE = "nexaflow_refresh_token"
REFRESH_TOKEN_COOKIE_PATH = "/api/v1/auth"


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_reset(
    payload: PasswordResetRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await request_password_reset(
        db,
        payload.email,
        settings,
        get_request_ip(request),
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def confirm_reset(
    payload: PasswordResetConfirmRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await confirm_password_reset(db, payload.token, payload.new_password, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invitations/accept", response_model=UserResponse)
async def accept_invitation(
    payload: WorkspaceInvitationAcceptRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """
    Accepts a workspace invitation and returns the created user profile.
    
    Parameters:
    	payload (WorkspaceInvitationAcceptRequest): Invitation acceptance data.
    	db (AsyncSession): Database session used to process the invitation.
    
    Returns:
    	UserResponse: The user associated with the accepted invitation.
    """
    return await accept_workspace_invitation(db, payload, settings)


def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    """Sets the refresh-token cookie on the response using the configured expiration and security attributes."""
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
    """
    Authenticate the user and issue access credentials.
    
    Parameters:
        payload (LoginRequest): User credentials used for authentication.
        request (Request): Incoming request used to capture client metadata.
        response (Response): Response on which the refresh-token cookie is set.
    
    Returns:
        TokenResponse: Access-token data for the authenticated user.
    """
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
    """Revoke the current refresh token and clear its authentication cookie."""
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
    """
    List the authenticated user's refresh-token sessions.
    
    Parameters:
    	user (User): The authenticated user.
    	refresh_token (str | None): The refresh token from the current session, when available.
    
    Returns:
    	list[RefreshSessionResponse]: The user's refresh-session details.
    """
    return await list_user_sessions(db, user, refresh_token)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """
    Revoke a refresh session belonging to the current user.
    
    Parameters:
    	session_id (str): Identifier of the session to revoke.
    """
    await revoke_user_session(db, user.id, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_other_sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE)] = None,
) -> Response:
    """
    Revoke refresh sessions for the current user, preserving the active session only when its token is supplied and valid.
    
    Parameters:
    	user (User): The authenticated user whose sessions are revoked.
        refresh_token (str | None): The current refresh token; without a valid token, all sessions may be revoked.
    
    Returns:
    	Response: An HTTP 204 response.
    """
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
    """
    Change the current user's password and issue a replacement refresh session.
    
    Parameters:
        payload (ChangePasswordRequest): Contains the current and new passwords.
    
    Returns:
        Response: An HTTP 204 response with the replacement refresh-token cookie.
    """
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
