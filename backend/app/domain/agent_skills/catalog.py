"""Render the authorized, pinned Skill catalog for model contexts."""

import json

from app.entities.agent_skills import AgentSkillSnapshot


def skill_execution_context(skills: list[AgentSkillSnapshot]) -> str:
    """Expose only the pinned catalog; load_skill provides full instructions."""
    if not skills:
        return ""
    catalog = [
        {
            "name": skill.name,
            "description": skill.description,
            "version_id": skill.version_id,
            "intents": skill.definition.get("intents", []),
        }
        for skill in skills
    ]
    return (
        "Available Skills (authorized pinned versions):\n"
        + json.dumps(catalog, ensure_ascii=False)
        + "\nBefore using a Skill, call load_skill with its version_id to read its full instructions. "
        "Skills guide tasks; their executable capabilities are separate tools.\n"
    )


__all__ = [
    "skill_execution_context",
]
