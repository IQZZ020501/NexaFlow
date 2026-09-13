"""Domain-level Agent Skill binding and snapshot resolution."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agent_skills.access import (
    AGENT_SKILL_RESOURCE_TYPE,
    evaluate_agent_skill_access,
    require_agent_skill_use,
    require_agent_skill_view,
)
from app.domain.agent_skills.contracts import build_agent_skill_snapshot
from app.domain.knowledge.service import get_knowledge_base, require_knowledge_base_permission
from app.domain.tools.access.bindings import resolve_tool_refs_for_actor
from app.entities.agent_skills import (
    AgentSkill,
    AgentSkillBinding,
    AgentSkillRef,
    AgentSkillSnapshot,
    AgentSkillVersion,
)
from app.entities.identity.user import User
from app.entities.tools import ToolRef
from app.infra.db.repositories.agent_skills import repository
from app.infra.db.repositories.identity import users as user_repository
from app.infra.db.repositories.workspaces import repository as workspace_repository
from app.infra.db.repositories.workspaces import resource_permissions
from app.schemas.agent_skills.contracts import AgentSkillDefinition, AgentSkillRefSchema


MAX_AGENT_SKILLS = 4


async def _skill_access(
    db: AsyncSession,
    skill: AgentSkill,
    actor: User,
    workspace_role: str | None,
):
    grant = await resource_permissions.get_user_grant(
        db,
        skill.workspace_id,
        AGENT_SKILL_RESOURCE_TYPE,
        skill.id,
        actor.id,
    )
    return evaluate_agent_skill_access(skill, actor, workspace_role, grant)


async def _get_visible_skill(
    db: AsyncSession,
    workspace_id: str,
    skill_id: str,
    actor: User,
    workspace_role: str | None,
) -> tuple[AgentSkill, object]:
    skill = await repository.get_agent_skill(db, workspace_id, skill_id)
    if skill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent Skill not found.")
    access = await _skill_access(db, skill, actor, workspace_role)
    require_agent_skill_view(access)
    return skill, access


async def resolve_agent_skill_refs(
    db: AsyncSession,
    workspace_id: str,
    references: list[AgentSkillRefSchema],
    actor: User,
    workspace_role: str | None,
) -> list[AgentSkillSnapshot]:
    if len(references) > MAX_AGENT_SKILLS or len(
        {reference.skill_id for reference in references}
    ) != len(references):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Agent Skill references must be unique and within the configured limit.",
        )
    snapshots: list[AgentSkillSnapshot] = []
    for reference in references:
        skill, access = await _get_visible_skill(
            db, workspace_id, reference.skill_id, actor, workspace_role
        )
        require_agent_skill_use(access)
        if skill.status != "active":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Agent Skill is disabled.",
            )
        version = await repository.get_agent_skill_version(
            db, workspace_id, reference.version_id
        )
        if version is None or version.skill_id != skill.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Agent Skill version is not available for binding.",
            )
        snapshots.append(build_agent_skill_snapshot(version, actor.id))
    return sorted(snapshots, key=lambda item: (item.skill_id, item.version_id))


async def sync_agent_skill_bindings(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    snapshots: list[AgentSkillSnapshot],
    actor_id: str,
) -> None:
    await repository.replace_agent_skill_bindings(
        db,
        workspace_id,
        agent_id,
        [
            AgentSkillBinding(
                workspace_id=workspace_id,
                agent_id=agent_id,
                skill_id=snapshot.skill_id,
                skill_version_id=snapshot.version_id,
                bound_by_user_id=actor_id,
            )
            for snapshot in snapshots
        ],
    )


async def resolve_application_agent_skill_snapshots(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
) -> list[AgentSkillSnapshot]:
    snapshots: list[AgentSkillSnapshot] = []
    for binding, skill, version in await repository.list_agent_skill_snapshot_rows(
        db, workspace_id, agent_id
    ):
        binder = await user_repository.get_user_by_id(db, binding.bound_by_user_id)
        if binder is None or not binder.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Agent Skill binding permission is no longer valid.",
            )
        membership = await workspace_repository.get_workspace_membership(
            db, workspace_id, binder.id
        )
        role = membership.role if membership is not None else None
        access = await _skill_access(db, skill, binder, role)
        require_agent_skill_use(access)
        if skill.status != "active":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A bound Agent Skill is disabled."
            )
        snapshots.append(build_agent_skill_snapshot(version, binding.bound_by_user_id))
    return sorted(snapshots, key=lambda item: (item.skill_id, item.version_id))


async def list_agent_skill_ref_map(
    db: AsyncSession,
    workspace_id: str,
    agent_ids: list[str],
) -> dict[str, list[AgentSkillRef]]:
    bindings = await repository.list_agent_skill_binding_map(db, workspace_id, agent_ids)
    return {
        agent_id: [
            AgentSkillRef(skill_id=item.skill_id, version_id=item.skill_version_id)
            for item in items
        ]
        for agent_id, items in bindings.items()
    }


async def validate_skill_definition_resources(
    db: AsyncSession,
    workspace_id: str,
    definition: AgentSkillDefinition,
    actor: User,
    workspace_role: str | None,
) -> None:
    """Validate resources referenced by a draft before it is published."""
    for knowledge_base_id in definition.knowledge_base_ids:
        knowledge_base = await get_knowledge_base(db, workspace_id, knowledge_base_id)
        await require_knowledge_base_permission(
            db, knowledge_base, actor, {"view", "edit"}
        )
    await resolve_tool_refs_for_actor(
        db,
        workspace_id,
        [ToolRef(tool_id=item.tool_id, version_id=item.version_id) for item in definition.tools],
        actor,
        workspace_role,
    )


__all__ = [
    "list_agent_skill_ref_map",
    "resolve_agent_skill_refs",
    "resolve_application_agent_skill_snapshots",
    "sync_agent_skill_bindings",
    "validate_skill_definition_resources",
]
