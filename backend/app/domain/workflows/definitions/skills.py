"""Freeze selected Workflow Skills and derive their authorized capabilities."""

from fastapi import HTTPException

from app.domain.agent_skills.service import (
    resolve_agent_skill_refs,
    resolve_application_agent_skill_snapshots,
)
from app.domain.tools.catalog.service import (
    BUILTIN_SKILL_DEFINITIONS,
    build_shell_tool,
    build_skill_dependency_installer_tool,
    build_skill_script_tool,
    stable_catalog_id,
)
from app.domain.workflows.resources import workflow_skill_references
from app.entities.agent_skills import AgentSkillSnapshot
from app.schemas.agent_skills.contracts import AgentSkillRefSchema
from app.schemas.workflows.contracts import LlmNodeConfig


async def prepare_workflow_skills(
    db, workspace_id, graph, actor, workspace_role, binding_application_id=None
) -> list[AgentSkillSnapshot]:
    try:
        references = workflow_skill_references(graph)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if binding_application_id is None:
        skills = []
        for offset in range(0, len(references), 4):
            skills.extend(
                await resolve_agent_skill_refs(
                    db,
                    workspace_id,
                    [
                        AgentSkillRefSchema(skill_id=key, version_id=value)
                        for key, value in references[offset : offset + 4]
                    ],
                    actor,
                    workspace_role,
                )
            )
    else:
        available = (
            {
                (item.skill_id, item.version_id): item
                for item in await resolve_application_agent_skill_snapshots(
                    db, workspace_id, binding_application_id
                )
            }
            if references
            else {}
        )
        try:
            skills = [available[item] for item in references]
        except KeyError as exc:
            raise HTTPException(
                409, "Workflow Skill binding is missing or stale."
            ) from exc
    by_ref = {(item.skill_id, item.version_id): item for item in skills}
    guides = {
        stable_catalog_id(f"tool:{workspace_id}:builtin:skill:{name}")
        for name, *_ in BUILTIN_SKILL_DEFINITIONS
    }
    for node in graph.nodes:
        if node.data.type != "llm":
            continue
        config = LlmNodeConfig.model_validate(node.data.config)
        selected = [by_ref[(item.skill_id, item.version_id)] for item in config.skills]
        implicit = [
            ref for skill in selected for ref in skill.definition.get("tools", [])
        ]
        builders = []
        if selected or any(item.tool_id in guides for item in config.tools):
            builders.append(build_shell_tool)
        if any(
            path.endswith((".py", ".js"))
            for skill in selected
            for path in skill.definition.get("files", {})
        ):
            builders.extend(
                [build_skill_script_tool, build_skill_dependency_installer_tool]
            )
        for builder in builders:
            tool, version, _ = builder(workspace_id)
            implicit.append({"tool_id": tool.id, "version_id": version.id})
        # Client-provided derived references are always replaced, including on removal.
        node.data.config = {**node.data.config, "capability_tools": implicit}
    return skills
