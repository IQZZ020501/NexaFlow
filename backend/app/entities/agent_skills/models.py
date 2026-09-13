from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.entities.defaults import new_id, utc_now

AgentSkillGrant = Literal["view", "use"]


@dataclass
class AgentSkill:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    name: str = ""
    description: str = ""
    draft_definition: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    current_published_version_id: str | None = None
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class AgentSkillRef:
    skill_id: str
    version_id: str

    def __post_init__(self) -> None:
        if not self.skill_id.strip() or not self.version_id.strip():
            raise ValueError("Agent Skill references require skill and version IDs.")


@dataclass
class AgentSkillVersion:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    skill_id: str = ""
    version_number: int = 1
    schema_version: int = 1
    name: str = ""
    description: str = ""
    definition_snapshot: dict[str, Any] = field(default_factory=dict)
    definition_hash: str = ""
    published_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class AgentSkillBinding:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    agent_id: str = ""
    skill_id: str = ""
    skill_version_id: str = ""
    bound_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class AgentSkillSnapshot:
    schema_version: int
    skill_id: str
    version_id: str
    version_number: int
    name: str
    description: str
    definition: dict[str, Any]
    definition_hash: str
    bound_by_user_id: str
