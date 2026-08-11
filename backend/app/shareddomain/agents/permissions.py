"""Agent access permission rules."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.agents import Agent
from app.entities.resource_permission import ResourcePermission
from app.entities.user import User
from app.infrastructure.repositories import resource_permission as permission_repository
from app.schemas.agent import AgentPermissionResponse
from app.schemas.user import user_to_response
from app.shareddomain.audit.services import record_audit_log

AGENT_RESOURCE_TYPE = "agent"
AGENT_VIEW_PERMISSION = "view"


def validate_agent_permission(permission: str) -> None:
    if permission != AGENT_VIEW_PERMISSION:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Invalid Agent permission.",
        )


def effective_agent_permission(
    agent: Agent,
    actor: User,
    workspace_role: str | None,
    grant: ResourcePermission | None = None,
) -> str:
    if workspace_role == "admin" or agent.created_by_user_id == actor.id:
        return "edit"
    if grant is not None and grant.permission == AGENT_VIEW_PERMISSION:
        return AGENT_VIEW_PERMISSION
    return "none"


def can_edit_agent(
    agent: Agent,
    actor: User,
    workspace_role: str | None,
) -> bool:
    return effective_agent_permission(agent, actor, workspace_role) == "edit"


def require_agent_edit(
    agent: Agent,
    actor: User,
    workspace_role: str | None,
) -> None:
    if can_edit_agent(agent, actor, workspace_role):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent owner required.")


async def get_agent_grant(
    db: AsyncSession,
    agent: Agent,
    user_id: str,
) -> ResourcePermission | None:
    return await permission_repository.get_user_grant(
        db,
        agent.workspace_id,
        AGENT_RESOURCE_TYPE,
        agent.id,
        user_id,
    )


async def require_agent_view(
    db: AsyncSession,
    agent: Agent,
    actor: User,
    workspace_role: str | None,
) -> str:
    if can_edit_agent(agent, actor, workspace_role):
        return "edit"
    permission = effective_agent_permission(
        agent,
        actor,
        workspace_role,
        await get_agent_grant(db, agent, actor.id),
    )
    if permission == AGENT_VIEW_PERMISSION:
        return permission
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent access denied.")


async def list_agent_permissions(
    db: AsyncSession,
    agent: Agent,
    limit: int | None = None,
    offset: int = 0,
) -> list[AgentPermissionResponse]:
    rows = await permission_repository.list_resource_permission_rows(
        db,
        agent.workspace_id,
        AGENT_RESOURCE_TYPE,
        agent.id,
        limit,
        offset,
    )
    return [
        AgentPermissionResponse(
            user=user_to_response(user, [], []),
            permission=AGENT_VIEW_PERMISSION,
        )
        for _permission, user in rows
    ]


async def upsert_agent_permission(
    db: AsyncSession,
    agent: Agent,
    target_user_id: str,
    permission: str,
    actor: User,
) -> AgentPermissionResponse:
    validate_agent_permission(permission)
    target = await permission_repository.get_active_workspace_member(
        db,
        agent.workspace_id,
        target_user_id,
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace member not found.")

    resource_permission = await get_agent_grant(db, agent, target_user_id)
    if resource_permission is None:
        resource_permission = ResourcePermission(
            workspace_id=agent.workspace_id,
            resource_type=AGENT_RESOURCE_TYPE,
            resource_id=agent.id,
            user_id=target_user_id,
            permission=AGENT_VIEW_PERMISSION,
            created_by_user_id=actor.id,
        )
        await permission_repository.create_resource_permission(db, resource_permission)
    else:
        resource_permission.permission = AGENT_VIEW_PERMISSION
        await permission_repository.save_resource_permission(db, resource_permission)

    record_audit_log(
        db,
        actor,
        "resource_permission.grant",
        AGENT_RESOURCE_TYPE,
        agent.id,
        agent.name,
        {"user_id": target_user_id, "permission": AGENT_VIEW_PERMISSION},
        workspace_id=agent.workspace_id,
    )
    await db.commit()
    return AgentPermissionResponse(
        user=user_to_response(target, [], []),
        permission=AGENT_VIEW_PERMISSION,
    )


async def revoke_agent_permission(
    db: AsyncSession,
    agent: Agent,
    target_user_id: str,
    actor: User,
) -> None:
    deleted_count = await permission_repository.delete_resource_permission(
        db,
        agent.workspace_id,
        AGENT_RESOURCE_TYPE,
        agent.id,
        target_user_id,
    )
    if deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource permission not found.")

    record_audit_log(
        db,
        actor,
        "resource_permission.revoke",
        AGENT_RESOURCE_TYPE,
        agent.id,
        agent.name,
        {"user_id": target_user_id},
        workspace_id=agent.workspace_id,
    )
    await db.commit()
