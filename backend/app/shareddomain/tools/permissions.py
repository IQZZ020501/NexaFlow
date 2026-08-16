"""Unified Tool ownership and grant rules."""

from dataclasses import dataclass
from typing import Literal, cast

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.resource_permission import ResourcePermission
from app.entities.tools import Tool, ToolAccess, ToolGrant, effective_tool_access
from app.entities.user import User
from app.shareddomain.audit.services import record_audit_log

ToolPermissionLabel = Literal["owner", "admin", "view", "use"]
TOOL_RESOURCE_TYPE = "tool"
TOOL_GRANT_PERMISSIONS: frozenset[str] = frozenset({"view", "use"})


@dataclass(frozen=True)
class ToolAuthorization:
    access: ToolAccess
    permission: ToolPermissionLabel | None


@dataclass(frozen=True)
class ToolPermissionEntry:
    grant: ResourcePermission
    user: User


def has_tool_workspace_access(actor: User, workspace_role: str | None) -> bool:
    return actor.is_active and (
        actor.is_global_admin or workspace_role in {"admin", "member"}
    )


def evaluate_tool_authorization(
    tool: Tool,
    actor: User,
    workspace_role: str | None,
    grant: ResourcePermission | None,
) -> ToolAuthorization:
    if not has_tool_workspace_access(actor, workspace_role):
        return ToolAuthorization(
            access=ToolAccess(can_view=False, can_use=False, can_manage=False),
            permission=None,
        )
    is_owner = tool.created_by_user_id == actor.id
    is_admin = actor.is_global_admin or workspace_role == "admin"
    grant_permission: ToolGrant | None = None
    if grant is not None and grant.permission in TOOL_GRANT_PERMISSIONS:
        grant_permission = cast(ToolGrant, grant.permission)
    if tool.kind == "builtin":
        grant_permission = "use"

    access = effective_tool_access(
        is_owner=is_owner,
        is_workspace_admin=is_admin,
        grant=grant_permission,
    )
    if is_owner:
        permission: ToolPermissionLabel | None = "owner"
    elif is_admin:
        permission = "admin"
    else:
        permission = grant_permission
    return ToolAuthorization(access=access, permission=permission)


def require_tool_view(authorization: ToolAuthorization) -> ToolAuthorization:
    if authorization.access.can_view:
        return authorization
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found.")


def require_tool_use(authorization: ToolAuthorization) -> ToolAuthorization:
    require_tool_view(authorization)
    if authorization.access.can_use:
        return authorization
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Tool use permission required.")


def require_tool_manage(authorization: ToolAuthorization) -> ToolAuthorization:
    require_tool_view(authorization)
    if authorization.access.can_manage:
        return authorization
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Tool owner or admin required.")


def validate_tool_permission(permission: str) -> None:
    if permission not in TOOL_GRANT_PERMISSIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Invalid Tool permission.",
        )


async def _require_managed_tool(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
    *,
    lock: bool,
) -> Tool:
    from app.infrastructure.repositories import resource_permission as repository
    from app.infrastructure.repositories import tools as tool_repository

    getter = tool_repository.lock_tool if lock else tool_repository.get_tool
    tool = await getter(db, workspace_id, tool_id)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found.")
    grant = await repository.get_user_grant(
        db,
        workspace_id,
        TOOL_RESOURCE_TYPE,
        tool.id,
        actor.id,
    )
    require_tool_manage(
        evaluate_tool_authorization(tool, actor, workspace_role, grant)
    )
    return tool


async def list_tool_permissions(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int | None = None,
    offset: int = 0,
) -> list[ToolPermissionEntry]:
    from app.infrastructure.repositories import resource_permission as repository

    tool = await _require_managed_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=False,
    )
    rows = await repository.list_resource_permission_rows(
        db,
        workspace_id,
        TOOL_RESOURCE_TYPE,
        tool.id,
        limit,
        offset,
    )
    return [ToolPermissionEntry(grant=grant, user=user) for grant, user in rows]


async def upsert_tool_permission(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    target_user_id: str,
    permission: str,
    actor: User,
    workspace_role: str | None,
) -> ToolPermissionEntry:
    from app.infrastructure.repositories import resource_permission as repository

    tool = await _require_managed_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=True,
    )
    validate_tool_permission(permission)
    target = await repository.get_active_workspace_member(
        db,
        workspace_id,
        target_user_id,
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")
    if target.id == actor.id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Tool permissions cannot be granted to yourself.",
        )
    if target.id == tool.created_by_user_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Tool owners do not require explicit permissions.",
        )

    previous = await repository.get_user_grant(
        db,
        workspace_id,
        TOOL_RESOURCE_TYPE,
        tool.id,
        target.id,
    )
    grant = await repository.upsert_resource_permission(
        db,
        ResourcePermission(
            workspace_id=workspace_id,
            resource_type=TOOL_RESOURCE_TYPE,
            resource_id=tool.id,
            user_id=target.id,
            permission=permission,
            created_by_user_id=actor.id,
        ),
    )
    record_audit_log(
        db,
        actor,
        "resource_permission.grant",
        TOOL_RESOURCE_TYPE,
        tool.id,
        tool.function_name,
        {
            "user_id": target.id,
            "permission": permission,
            "previous_permission": previous.permission if previous else None,
        },
        workspace_id=workspace_id,
    )
    await db.commit()
    return ToolPermissionEntry(grant=grant, user=target)


async def revoke_tool_permission(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    target_user_id: str,
    actor: User,
    workspace_role: str | None,
) -> None:
    from app.infrastructure.repositories import resource_permission as repository

    tool = await _require_managed_tool(
        db,
        workspace_id,
        tool_id,
        actor,
        workspace_role,
        lock=True,
    )
    deleted_count = await repository.delete_resource_permission(
        db,
        workspace_id,
        TOOL_RESOURCE_TYPE,
        tool.id,
        target_user_id,
    )
    if deleted_count == 0:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Tool permission not found.",
        )
    record_audit_log(
        db,
        actor,
        "resource_permission.revoke",
        TOOL_RESOURCE_TYPE,
        tool.id,
        tool.function_name,
        {"user_id": target_user_id},
        workspace_id=workspace_id,
    )
    await db.commit()


__all__ = [
    "ToolAuthorization",
    "ToolPermissionEntry",
    "ToolPermissionLabel",
    "evaluate_tool_authorization",
    "has_tool_workspace_access",
    "list_tool_permissions",
    "require_tool_manage",
    "require_tool_use",
    "require_tool_view",
    "revoke_tool_permission",
    "upsert_tool_permission",
    "validate_tool_permission",
]
