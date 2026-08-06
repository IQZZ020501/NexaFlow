import logging
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.workspace import WorkspaceContext, build_workspace_context
from app.infrastructure.config import Settings
from app.infrastructure.logger import get_logger, log_event
from app.infrastructure.session import get_db
from app.entities.user import User
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.security import decode_access_token

logger = get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        log_event(logger, logging.WARNING, "Authentication failed.", reason="missing_token")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")

    user_id = decode_access_token(credentials.credentials, settings)
    if user_id is None:
        log_event(logger, logging.WARNING, "Authentication failed.", reason="invalid_token")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token.")

    user = await user_repository.get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        log_event(
            logger,
            logging.WARNING,
            "Authentication failed.",
            reason="user_inactive",
            user_id=user_id,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token.")
    return user


async def require_password_changed(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required.")
    return user


async def require_global_admin(
    user: Annotated[User, Depends(require_password_changed)],
) -> User:
    if not user.is_global_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Global admin required.")
    return user


async def get_workspace_context_from_path(
    workspace_id: str,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceContext:
    return await build_workspace_context(db, user, workspace_id)


def require_workspace_path_role(
    roles: set[str],
) -> Callable[[WorkspaceContext], WorkspaceContext]:
    async def dependency(
        context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    ) -> WorkspaceContext:
        return require_context_role(context, roles)

    return dependency


def require_context_role(
    context: WorkspaceContext,
    roles: set[str],
) -> WorkspaceContext:
    if context.membership_role not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace role required.")
    return context
