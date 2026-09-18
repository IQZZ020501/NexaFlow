from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.entities.tools import validate_tool_json_schema
from app.schemas.identity.contracts import UserResponse
from app.schemas.tools.contracts import ToolRefSchema


class AgentSkillRefSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(min_length=1, max_length=36)
    version_id: str = Field(min_length=1, max_length=36)


class AgentSkillRetrievalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_calls: int = Field(default=3, ge=0, le=12)
    max_rounds: int = Field(default=2, ge=0, le=8)
    min_evidence_items: int = Field(default=0, ge=0, le=20)
    require_source_diversity: bool = False

    @model_validator(mode="after")
    def validate_rounds(self) -> "AgentSkillRetrievalPolicy":
        if self.max_calls == 0 and self.max_rounds != 0:
            raise ValueError("Retrieval rounds require at least one retrieval call.")
        return self


class AgentSkillBudgetPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_runtime_seconds: float = Field(default=300, gt=0, le=1800)
    max_turns: int = Field(default=8, ge=1, le=64)
    max_tool_calls: int = Field(default=12, ge=1, le=128)
    max_model_tokens: int = Field(
        default=100_000, ge=1, le=1_000_000, deprecated=True
    )


class AgentSkillStopPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_no_progress_rounds: int = Field(default=2, ge=1, le=8)
    allow_best_effort: bool = True


class AgentSkillGuardrails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_external_reads: bool = False
    allow_external_writes: bool = False
    require_approval_for_external_writes: bool = True

    @model_validator(mode="after")
    def validate_external_write_approval(self) -> "AgentSkillGuardrails":
        if self.allow_external_writes and not self.require_approval_for_external_writes:
            raise ValueError("External writes must require approval.")
        return self


class AgentSkillEvaluationRubric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Read old versioned definitions without activating a retired verifier.
    require_grounding: bool = Field(default=False, deprecated=True)
    min_evidence_count: int = Field(default=0, ge=0, le=20, deprecated=True)
    max_tool_failures: int = Field(default=0, ge=0, le=20)


class AgentSkillDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intents: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        min_length=1, max_length=16
    )
    instructions: str = Field(min_length=1, max_length=12_000)
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "additionalProperties": False}
    )
    output_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "additionalProperties": False}
    )
    knowledge_base_ids: list[
        Annotated[str, Field(min_length=1, max_length=36)]
    ] = Field(default_factory=list, max_length=4)
    tools: list[ToolRefSchema] = Field(default_factory=list, max_length=12)
    retrieval: AgentSkillRetrievalPolicy = Field(
        default_factory=AgentSkillRetrievalPolicy, deprecated=True
    )
    budgets: AgentSkillBudgetPolicy = Field(default_factory=AgentSkillBudgetPolicy)
    stop: AgentSkillStopPolicy = Field(
        default_factory=AgentSkillStopPolicy, deprecated=True
    )
    guardrails: AgentSkillGuardrails = Field(default_factory=AgentSkillGuardrails)
    evaluation: AgentSkillEvaluationRubric = Field(
        default_factory=AgentSkillEvaluationRubric
    )

    @field_validator("intents")
    @classmethod
    def normalize_intents(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Agent Skill intents must be unique.")
        return normalized

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_tool_json_schema(value)

    @model_validator(mode="after")
    def validate_resource_references(self) -> "AgentSkillDefinition":
        if len(set(self.knowledge_base_ids)) != len(self.knowledge_base_ids):
            raise ValueError("Agent Skill knowledge references must be unique.")
        if len({item.tool_id for item in self.tools}) != len(self.tools):
            raise ValueError("Agent Skill Tool references must be unique.")
        return self


class AgentSkillCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    definition: AgentSkillDefinition


class AgentSkillUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    definition: AgentSkillDefinition | None = None
    status: Literal["active", "disabled"] | None = None


class AgentSkillVersionResponse(BaseModel):
    id: str
    workspace_id: str
    skill_id: str
    version_number: int
    schema_version: int
    name: str
    description: str
    definition: AgentSkillDefinition
    definition_hash: str
    published_by_user_id: str
    created_at: datetime


class AgentSkillResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    definition: AgentSkillDefinition
    status: Literal["active", "disabled"]
    current_published_version_id: str | None
    current_version_number: int | None = None
    has_unpublished_changes: bool
    permission: Literal["owner", "admin", "view", "use"]
    can_manage: bool
    can_use: bool
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class AgentSkillPermissionResponse(BaseModel):
    user: UserResponse
    permission: Literal["view", "use"]


class AgentSkillPermissionUpsertRequest(BaseModel):
    permission: Literal["view", "use"]
