from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


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

    @model_validator(mode="after")
    def validate_action(self) -> "KnowledgeGraphReviewDecisionRequest":
        if self.canonical_name is not None:
            self.canonical_name = self.canonical_name.strip()
        if self.entity_type is not None:
            self.entity_type = self.entity_type.strip()
        if self.action == "merge_entities" and not self.target_entity_id:
            raise ValueError("Merge decisions require a target entity.")
        if self.action == "split_entity":
            if not self.canonical_name or not self.entity_type:
                raise ValueError(
                    "Split decisions require a canonical name and entity type."
                )
            if not self.mention_ids and not self.claim_ids:
                raise ValueError(
                    "Split decisions require at least one mention or claim."
                )
        return self


class KnowledgeGraphSettingsResponse(BaseModel):
    enabled: bool
    extraction_model_id: str | None
    active_schema_id: str | None
    active_revision_id: str | None


class KnowledgeGraphSettingsUpdateRequest(BaseModel):
    enabled: bool
    extraction_model_id: str | None = Field(default=None, max_length=36)


class KnowledgeGraphSchemaUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    graph_schema: dict[str, Any] = Field(alias="schema_json")


class KnowledgeGraphSchemaResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    version: int
    status: Literal["draft", "active", "retired"]
    graph_schema: dict[str, Any] = Field(alias="schema_json")
    schema_hash: str


class KnowledgeGraphStatusResponse(BaseModel):
    enabled: bool
    active_schema_id: str | None
    active_revision_id: str | None
    revision_no: int | None
    revision_status: str | None
    source_watermark: str | None
    stats: dict[str, Any]
    model_usage: dict[str, Any]
    pending_review_count: int
    last_error: str | None
    published_at: datetime | None


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


class KnowledgeGraphEntityDetailResponse(KnowledgeGraphEntityResponse):
    claims: list[KnowledgeGraphClaimResponse] = Field(default_factory=list)
    evidence: list[KnowledgeGraphEvidenceResponse] = Field(default_factory=list)


class KnowledgeGraphReviewItemResponse(BaseModel):
    id: str
    kind: str
    payload: dict[str, Any]
    status: str
    revision_id: str
    created_at: datetime


class KnowledgeGraphEntityListResponse(BaseModel):
    items: list[KnowledgeGraphEntityResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class KnowledgeGraphReviewListResponse(BaseModel):
    items: list[KnowledgeGraphReviewItemResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class KnowledgeGraphPathRequest(BaseModel):
    source_entity: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]
    target_entity: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]
    max_hops: int = Field(default=6, ge=1, le=8)
    relation_filters: list[str] = Field(default_factory=list, max_length=32)


class KnowledgeGraphNeighborhoodRequest(BaseModel):
    entity: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    ]
    max_hops: int = Field(default=2, ge=1, le=3)
    relation_filters: list[str] = Field(default_factory=list, max_length=32)


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
