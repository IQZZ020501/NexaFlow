from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_settings, require_global_admin
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.entities.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    UserCreateRequest,
    UserPasswordResetResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.application.identity import (
    change_user_password,
    create_user,
    delete_user_permanently,
    get_user,
    list_users,
    update_user,
)
from app.application.sessions import (
    list_user_sessions,
    revoke_all_user_sessions,
    revoke_user_session,
)
from app.schemas.user import RefreshSessionResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_all_users(
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserResponse]:
    return await list_users(db, limit, offset)


@router.post(
    "",
    response_model=UserPasswordResetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_user(
    payload: UserCreateRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPasswordResetResponse:
    return await create_user(db, payload, actor, settings)


@router.patch("/{user_id}", response_model=UserResponse)
async def patch_user(
    user_id: str,
    payload: UserUpdateRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await get_user(db, user_id)
    return await update_user(db, user, actor, payload)


@router.post(
    "/{user_id}/change-password",
    response_model=UserResponse,
)
async def change_managed_user_password(
    user_id: str,
    payload: ChangePasswordRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Change the password for a managed user.
    
    Parameters:
    	user_id (str): Identifier of the user whose password is changed.
    	payload (ChangePasswordRequest): Request containing the new password.
    	actor (User): Global administrator authorizing the change.
    
    Returns:
    	UserResponse: The updated user.
    """
    user = await get_user(db, user_id)
    return await change_user_password(db, user, actor, payload.new_password)


@router.get("/{user_id}/sessions", response_model=list[RefreshSessionResponse])
async def list_managed_user_sessions(
    user_id: str,
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[RefreshSessionResponse]:
    """List all active sessions for a managed user.
    
    Parameters:
    	user_id (str): The identifier of the user whose sessions to retrieve.
    
    Returns:
    	list[RefreshSessionResponse]: The user's refresh sessions.
    """
    user = await get_user(db, user_id)
    return await list_user_sessions(db, user)


@router.delete("/{user_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_managed_user_session(
    user_id: str,
    session_id: str,
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Revoke a specific session belonging to a managed user.
    
    Parameters:
        user_id (str): Identifier of the user whose session is revoked.
        session_id (str): Identifier of the session to revoke.
    """
    user = await get_user(db, user_id)
    await revoke_user_session(db, user.id, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{user_id}/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_managed_user_sessions(
    user_id: str,
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Revoke all active sessions for a managed user.
    
    Parameters:
    	user_id (str): Identifier of the user whose sessions are revoked.
    """
    user = await get_user(db, user_id)
    await revoke_all_user_sessions(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Permanently delete a user authorized by a global administrator.
    
    Parameters:
    	user_id (str): Identifier of the user to delete
    	actor (User): Global administrator authorizing the deletion
    
    Returns:
    	Response: An HTTP 204 response
    """
    user = await get_user(db, user_id)
    await delete_user_permanently(db, user, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
