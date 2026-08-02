from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_global_admin
from app.core.session import get_db
from app.models.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    UserCreateRequest,
    UserPasswordResetResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.services.auth import (
    change_user_password,
    create_user,
    delete_user_permanently,
    get_user,
    list_users,
    update_user,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_all_users(
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserResponse]:
    return await list_users(db)


@router.post(
    "",
    response_model=UserPasswordResetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_user(
    payload: UserCreateRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPasswordResetResponse:
    return await create_user(db, payload, actor)


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
    user = await get_user(db, user_id)
    return await change_user_password(db, user, actor, payload.new_password)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    user = await get_user(db, user_id)
    await delete_user_permanently(db, user, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
