from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class GraphQueryPlan(BaseModel):
    intent: Literal[
        "none",
        "fact",
        "profile",
        "path",
        "neighborhood",
        "synthesis",
    ]
    source_text: str | None = Field(default=None, max_length=500)
    target_text: str | None = Field(default=None, max_length=500)
    entity_terms: list[str] = Field(default_factory=list, max_length=16)
    relation_filters: list[str] = Field(default_factory=list, max_length=32)
    max_hops: int = Field(default=6, ge=1, le=8)


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


class KnowledgeGraphEntityResponse(BaseModel):
    id: str
    entity_type: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    profile_markdown: str = ""
    component_id: str | None = None
    degree: int = 0


class KnowledgeGraphEvidenceResponse(BaseModel):
    id: str
    claim_id: str
    document_id: str
    document_filename: str
    chunk_id: str
    quote: str
    start_offset: int
    end_offset: int
    source_kind: str


class KnowledgeGraphClaimResponse(BaseModel):
    id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str | None
    object_value: Any | None
    properties: dict[str, Any] = Field(default_factory=dict)
    quality_score: float
    support_count: int
    evidence_ids: list[str] = Field(default_factory=list)


class KnowledgeGraphPathStepResponse(BaseModel):
    claim_id: str
    predicate: str
    source_entity_id: str
    target_entity_id: str
    semantic_direction: Literal["forward", "reverse"]
    quality_score: float
    support_count: int
    evidence_ids: list[str] = Field(default_factory=list)


class KnowledgeGraphPathResponse(BaseModel):
    nodes: list[KnowledgeGraphEntityResponse]
    steps: list[KnowledgeGraphPathStepResponse]


class KnowledgeGraphQueryResultResponse(BaseModel):
    revision_id: str
    operation: str
    resolved_entities: list[KnowledgeGraphEntityResponse]
    nodes: list[KnowledgeGraphEntityResponse]
    claims: list[KnowledgeGraphClaimResponse]
    paths: list[KnowledgeGraphPathResponse]
    evidence: list[KnowledgeGraphEvidenceResponse]
    visited_nodes: int
    truncated: bool
    limit_reason: str | None = None
