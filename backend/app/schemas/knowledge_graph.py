from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class KnowledgeGraphImportEntity(BaseModel):
    entity_type: str = Field(min_length=1, max_length=80)
    canonical_name: str = Field(min_length=1, max_length=500)
    external_key: str | None = Field(default=None, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    properties: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraphImportRecord(BaseModel):
    subject: KnowledgeGraphImportEntity
    predicate: str = Field(min_length=1, max_length=80)
    object: KnowledgeGraphImportEntity | None = None
    value: Any | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    evidence: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_object(self) -> "KnowledgeGraphImportRecord":
        if (self.object is None) == (self.value is None):
            raise ValueError("Exactly one structured graph object is required.")
        return self


class KnowledgeGraphReviewDecisionRequest(BaseModel):
    action: Literal[
        "approve_claim",
        "reject_claim",
        "merge_entities",
        "split_entity",
    ]
    target_entity_id: str | None = Field(default=None, max_length=36)
    canonical_name: str | None = Field(default=None, max_length=500)
    entity_type: str | None = Field(default=None, max_length=80)
    mention_ids: list[str] = Field(default_factory=list, max_length=500)
    claim_ids: list[str] = Field(default_factory=list, max_length=500)
