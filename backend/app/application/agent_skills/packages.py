from app.domain.agent_skills.packages import inspect_skill_package
from app.schemas.agent_skills.contracts import AgentSkillCreateRequest


def inspect_import(filename: str, content: bytes) -> AgentSkillCreateRequest:
    return AgentSkillCreateRequest.model_validate(
        inspect_skill_package(filename, content)
    )
