from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.core.config import Settings
from nexaflow.db.session import get_db
from nexaflow.identity.deps import (
    get_current_user,
    get_settings,
    require_global_admin,
)
from nexaflow.identity.models import User
from nexaflow.identity.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    TokenResponse,
    UserCreateRequest,
    UserPasswordResetResponse,
    UserResponse,
    UserUpdateRequest,
)
from nexaflow.identity.services import (
    authenticate_user,
    change_password,
    create_user,
    deactivate_user,
    get_user,
    get_me,
    list_users,
    reset_user_password,
    update_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


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


@users_router.get("", response_model=list[UserResponse])
async def list_all_users(
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserResponse]:
    return await list_users(db)


@users_router.post(
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


@users_router.patch("/{user_id}", response_model=UserResponse)
async def patch_user(
    user_id: str,
    payload: UserUpdateRequest,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await get_user(db, user_id)
    return await update_user(db, user, actor, payload)


@users_router.post(
    "/{user_id}/reset-password",
    response_model=UserPasswordResetResponse,
)
async def reset_password(
    user_id: str,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPasswordResetResponse:
    user = await get_user(db, user_id)
    return await reset_user_password(db, user, actor)


@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    user = await get_user(db, user_id)
    await deactivate_user(db, user, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
