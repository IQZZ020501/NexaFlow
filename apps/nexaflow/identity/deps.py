from dataclasses import dataclass
from typing import Annotated, Callable

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexaflow.core.config import Settings
from nexaflow.db.session import get_db
from nexaflow.identity.models import User
from nexaflow.identity.security import decode_access_token
from nexaflow.workspaces.models import Workspace, WorkspaceMembership

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class WorkspaceContext:
    workspace: Workspace
    user: User
    membership_role: str | None


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")

    user_id = decode_access_token(credentials.credentials, settings)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token.")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
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


async def get_workspace_context(
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
) -> WorkspaceContext:
    if not workspace_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Workspace-ID is required.")

    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    if workspace.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace is not active.")

    membership = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if membership is None and not user.is_global_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace access denied.")

    return WorkspaceContext(
        workspace=workspace,
        user=user,
        membership_role=membership.role if membership else None,
    )


def require_workspace_role(roles: set[str]) -> Callable[[WorkspaceContext], WorkspaceContext]:
    async def dependency(
        context: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    ) -> WorkspaceContext:
        if context.user.is_global_admin:
            return context
        if context.membership_role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace role required.")
        return context

    return dependency
