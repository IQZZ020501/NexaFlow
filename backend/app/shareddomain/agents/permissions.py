"""Agent access permission rules."""

from fastapi import HTTPException, status

from app.entities.agents import Agent
from app.entities.resource_permission import ResourcePermission
from app.entities.user import User

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
