"""Use the Agent's pinned, lazy Skill catalog inside a Workflow LLM node."""

from nexaflow_extension_api import AgentExtension

from app.application.agent_skills.execution import require_pinned_skill_access
from app.domain.agent_skills.contracts import agent_skill_snapshot_from_payload
from app.domain.agents.runtime.capabilities import CapabilityRegistry
from app.domain.agents.runtime.extensions import ExtensionRuntime
from app.infra.db.session import get_session_factory


def workflow_skill_catalog(run, references, tools):
    available = {
        (item["skill_id"], item["version_id"]): item for item in run.skill_snapshots
    }
    skills = [
        agent_skill_snapshot_from_payload(available[(item.skill_id, item.version_id)])
        for item in references
    ]

    async def authorize(skill):
        async with get_session_factory()() as db:
            await require_pinned_skill_access(db, run.workspace_id, skill)

    return CapabilityRegistry(
        ExtensionRuntime(
            [AgentExtension(name="workflow", version="1", tools=tuple(tools))]
        ),
        skills,
        authorize_skill=authorize,
    )
