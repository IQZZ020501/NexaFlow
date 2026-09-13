from dataclasses import dataclass
from typing import Literal, cast

from fastapi import HTTPException, status

from app.entities.agent_skills import AgentSkill, AgentSkillGrant
from app.entities.identity.user import User
from app.entities.workspaces.resource_permissions import ResourcePermission


AGENT_SKILL_RESOURCE_TYPE = "agent_skill"
AGENT_SKILL_GRANTS = frozenset({"view", "use"})
AgentSkillPermissionLabel = Literal["owner", "admin", "view", "use"]


@dataclass(frozen=True)
class AgentSkillAccess:
    can_view: bool
    can_use: bool
    can_manage: bool
    permission: AgentSkillPermissionLabel | None


def evaluate_agent_skill_access(
    skill: AgentSkill,
    actor: User,
    workspace_role: str | None,
    grant: ResourcePermission | None,
) -> AgentSkillAccess:
    if not actor.is_active or (
        not actor.is_global_admin and workspace_role not in {"admin", "member"}
    ):
        return AgentSkillAccess(False, False, False, None)
    owner = skill.created_by_user_id == actor.id
    admin = actor.is_global_admin or workspace_role == "admin"
    permission: AgentSkillPermissionLabel | None = None
    if owner:
        permission = "owner"
    elif admin:
        permission = "admin"
    elif grant is not None and grant.permission in AGENT_SKILL_GRANTS:
        permission = cast(AgentSkillPermissionLabel, grant.permission)
    can_manage = owner or admin
    can_use = can_manage or permission == "use"
    return AgentSkillAccess(
        can_view=can_use or permission == "view",
        can_use=can_use,
        can_manage=can_manage,
        permission=permission,
    )


def require_agent_skill_view(access: AgentSkillAccess) -> None:
    if not access.can_view:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent Skill not found.")


def require_agent_skill_use(access: AgentSkillAccess) -> None:
    require_agent_skill_view(access)
    if not access.can_use:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Agent Skill use permission required."
        )


def require_agent_skill_manage(access: AgentSkillAccess) -> None:
    require_agent_skill_view(access)
    if not access.can_manage:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Agent Skill owner or admin required."
        )
