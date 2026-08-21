from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infrastructure.model_utils import new_id, utc_now

GRAPH_SCHEMA_DRAFT = "draft"
GRAPH_SCHEMA_ACTIVE = "active"
GRAPH_SCHEMA_RETIRED = "retired"
GRAPH_REVISION_BUILDING = "building"
GRAPH_REVISION_PUBLISHED = "published"
GRAPH_REVISION_FAILED = "failed"
GRAPH_REVISION_RETIRED = "retired"
GRAPH_ENTITY_ACTIVE = "active"
GRAPH_ENTITY_MERGED = "merged"
GRAPH_ENTITY_RETIRED = "retired"
GRAPH_CLAIM_CANDIDATE = "candidate"
GRAPH_CLAIM_ACTIVE = "active"
GRAPH_CLAIM_REJECTED = "rejected"
GRAPH_CLAIM_SUPERSEDED = "superseded"
GRAPH_EVIDENCE_ACTIVE = "active"
GRAPH_EVIDENCE_DELETED = "deleted"
GRAPH_EVIDENCE_INACCESSIBLE = "inaccessible"
GRAPH_REVIEW_OPEN = "open"
GRAPH_REVIEW_APPROVED = "approved"
GRAPH_REVIEW_REJECTED = "rejected"
GRAPH_REVIEW_RESOLVED = "resolved"


@dataclass
class KnowledgeGraphSchema:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    version: int = 1
    schema_json: dict[str, Any] = field(default_factory=dict)
    schema_hash: str = ""
    status: str = GRAPH_SCHEMA_DRAFT
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeGraphRevision:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    revision_no: int = 1
    schema_id: str = ""
    parent_revision_id: str | None = None
    status: str = GRAPH_REVISION_BUILDING
    source_watermark: str = ""
    stats_json: dict[str, Any] = field(default_factory=dict)
    model_usage_json: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    created_by_user_id: str = ""
    started_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeGraphRevisionChange:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    revision_id: str = ""
    sequence_no: int = 0
    record_kind: str = ""
    record_key: str = ""
    operation: str = "upsert"
    before_json: dict[str, Any] | None = None
    after_json: dict[str, Any] | None = None
    applied_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeGraphEntity:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    entity_type: str = ""
    canonical_name: str = ""
    normalized_name: str = ""
    external_key: str | None = None
    properties_json: dict[str, Any] = field(default_factory=dict)
    profile_markdown: str = ""
    profile_hash: str = ""
    profile_claim_ids: list[str] = field(default_factory=list)
    search_text: str = ""
    component_id: str | None = None
    degree: int = 0
    state: str = GRAPH_ENTITY_ACTIVE
    created_revision_id: str = ""
    last_published_revision_id: str = ""
    retired_revision_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeGraphAlias:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    entity_id: str = ""
    alias: str = ""
    normalized_alias: str = ""
    source: str = "generated"
    created_revision_id: str = ""
    last_published_revision_id: str = ""
    retired_revision_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeGraphMention:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    entity_id: str = ""
    document_id: str = ""
    chunk_id: str = ""
    surface_text: str = ""
    start_offset: int = 0
    end_offset: int = 0
    quote: str = ""
    resolution_method: str = ""
    created_revision_id: str = ""
    last_published_revision_id: str = ""
    retired_revision_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeGraphClaim:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    subject_entity_id: str = ""
    predicate: str = ""
    object_entity_id: str | None = None
    object_value_json: Any | None = None
    properties_json: dict[str, Any] = field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    status: str = GRAPH_CLAIM_CANDIDATE
    source_kind: str = "explicit_text"
    quality_score: float = 0.0
    support_count: int = 0
    fingerprint: str = ""
    created_revision_id: str = ""
    last_published_revision_id: str = ""
    retired_revision_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeGraphClaimEvidence:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    claim_id: str = ""
    document_id: str = ""
    chunk_id: str = ""
    quote: str = ""
    start_offset: int = 0
    end_offset: int = 0
    extractor_type: str = "rules"
    model_name: str = ""
    prompt_hash: str = ""
    schema_hash: str = ""
    evidence_state: str = GRAPH_EVIDENCE_ACTIVE
    created_revision_id: str = ""
    last_published_revision_id: str = ""
    retired_revision_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeGraphReviewItem:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    kind: str = ""
    payload_json: dict[str, Any] = field(default_factory=dict)
    status: str = GRAPH_REVIEW_OPEN
    decision_json: dict[str, Any] = field(default_factory=dict)
    revision_id: str = ""
    created_by_user_id: str = ""
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
