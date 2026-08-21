from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.knowledge_graph import KnowledgeGraphQueryResultResponse
from app.schemas.user import UserResponse


class KnowledgeBaseResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    status: str
    embedding_model_id: str | None
    reranker_model_id: str | None
    graph_enabled: bool = False
    active_graph_schema_id: str | None = None
    active_graph_revision_id: str | None = None
    graph_extraction_model_id: str | None = None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime
    permission: str


class KnowledgeBaseListItemResponse(KnowledgeBaseResponse):
    document_count: int
    char_count: int


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    embedding_model_id: str | None = Field(default=None, max_length=36)
    reranker_model_id: str | None = Field(default=None, max_length=36)
    graph_enabled: Literal[False] = False


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=20)
    embedding_model_id: str | None = Field(default=None, max_length=36)
    reranker_model_id: str | None = Field(default=None, max_length=36)


class KnowledgeModelTestRequest(BaseModel):
    query: str = Field(default="Hello", min_length=1, max_length=1000)
    documents: list[str] = Field(default_factory=lambda: ["Hello"], max_length=20)


class KnowledgeModelTestResponse(BaseModel):
    embedding_model_id: str
    embedding_dimensions: int
    reranker_model_id: str | None = None
    reranker_results: int = 0


class ResourcePermissionResponse(BaseModel):
    user: UserResponse
    permission: str


class ResourcePermissionUpsertRequest(BaseModel):
    permission: str = Field(min_length=1, max_length=20)


class KnowledgeBaseOwnerTransferRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)


class KnowledgeAttachmentResponse(BaseModel):
    id: str
    workspace_id: str
    knowledge_base_id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


KnowledgeImportMode = Literal["document", "qa"]


class KnowledgeDocumentCreateRequest(BaseModel):
    attachment_ids: list[str] = Field(min_length=1, max_length=30)
    staged: bool = True
    import_mode: KnowledgeImportMode = "document"


class KnowledgeDocumentResponse(BaseModel):
    id: str
    workspace_id: str
    knowledge_base_id: str
    filename: str
    content_type: str
    size_bytes: int
    attachment_id: str | None = None
    meta: dict[str, Any]
    status: str
    is_active: bool = True
    chunk_count: int = 0
    last_error: str | None = None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentStatusUpdateRequest(BaseModel):
    is_active: bool


class KnowledgeDocumentParseRequest(BaseModel):
    strategy: Literal["flat", "hierarchical"] = "flat"
    chunk_size: int = Field(default=1200, ge=100, le=8000)
    chunk_overlap: int = Field(default=150, ge=0, le=2000)
    split_separator: str = Field(default="\n\n", min_length=1, max_length=16)
    cleaning_rules: list[str] = Field(default_factory=list, max_length=3)
    auto_index: bool = True


class KnowledgeAssetResponse(BaseModel):
    id: str
    kind: Literal["image"]
    filename: str
    content_type: str
    size_bytes: int
    alt_text: str


class KnowledgeDocumentChunkResponse(BaseModel):
    id: str
    workspace_id: str
    knowledge_base_id: str
    document_id: str
    parent_id: str | None = None
    parent_title: str | None = None
    parent_index: int | None = None
    chunk_index: int
    start_offset: int | None = None
    end_offset: int | None = None
    content: str
    kind: Literal["document", "qa", "graph_record"] = "document"
    question: str | None = None
    source: str | None = None
    row_number: int | None = None
    char_count: int
    token_count: int
    vector_id: str | None = None
    status: str
    images: list[KnowledgeAssetResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentParagraphProblemRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class KnowledgeDocumentParagraphRequest(BaseModel):
    title: str = Field(default="", max_length=500)
    content: str = Field(min_length=1)
    problem_list: list[KnowledgeDocumentParagraphProblemRequest] = Field(default_factory=list)




class KnowledgeTaskResponse(BaseModel):
    id: str
    workspace_id: str
    knowledge_base_id: str
    document_id: str | None = None
    task_type: str
    status: str
    attempts: int
    max_attempts: int
    total_items: int
    processed_items: int
    last_error: str | None = None
    created_by_user_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


GraphMode = Literal["off", "auto", "path", "neighborhood"]


class KnowledgeQueryRequest(BaseModel):
    query: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    ]
    limit: int = Field(default=5, ge=1, le=20)
    search_mode: Literal["embedding", "keywords", "blend"] = "blend"
    # 归一化余弦相似度阈值（0–1，保留相似度不低于该值的命中）
    similarity: float | None = Field(default=None, ge=0, le=1)
    include_references: bool = False
    graph_mode: GraphMode = "auto"
    source_entity: str | None = Field(default=None, max_length=500)
    target_entity: str | None = Field(default=None, max_length=500)
    max_hops: int = Field(default=6, ge=1, le=8)
    relation_filters: list[str] = Field(default_factory=list, max_length=32)


class KnowledgeQueryHitResponse(BaseModel):
    chunk_id: str
    document_id: str
    document_filename: str
    parent_id: str | None = None
    parent_title: str | None = None
    parent_index: int | None = None
    section_path: list[str] = Field(default_factory=list, max_length=12)
    chunk_index: int
    content: str
    content_truncated: bool = False
    evidence_start_offset: int | None = Field(default=None, ge=0)
    evidence_end_offset: int | None = Field(default=None, ge=0)
    contributing_chunk_ids: list[str] = Field(default_factory=list, max_length=20)
    distance: float | None = None
    similarity: float | None = Field(default=None, ge=0, le=1)
    kind: Literal["document", "qa", "graph_record"] = "document"
    question: str | None = None
    source: str | None = None
    sources: list[str] = Field(default_factory=list, max_length=4)
    reference_hops: int = Field(default=0, ge=0, le=1)
    graph_claim_ids: list[str] = Field(default_factory=list, max_length=400)
    graph_hops: int = Field(default=0, ge=0, le=8)
    rerank_score: float | None = None


class KnowledgeRetrievalTraceResponse(BaseModel):
    trace_id: str
    search_mode: Literal["embedding", "keywords", "blend"]
    limit: int = Field(ge=1, le=20)
    min_similarity: float | None = Field(default=None, ge=0, le=1)
    max_distance: float | None = Field(default=None, ge=0, le=2)
    vector_candidates: int = Field(ge=0)
    keyword_candidates: int = Field(ge=0)
    reference_candidates: int = Field(ge=0)
    graph_mode: GraphMode = "auto"
    graph_intent: str | None = None
    graph_revision_id: str | None = None
    graph_entity_candidates: int = Field(default=0, ge=0)
    graph_profile_candidates: int = Field(default=0, ge=0)
    graph_claim_candidates: int = Field(default=0, ge=0)
    graph_path_count: int = Field(default=0, ge=0)
    graph_visited_nodes: int = Field(default=0, ge=0)
    graph_hops: int = Field(default=0, ge=0, le=8)
    graph_truncated: bool = False
    graph_limit_reason: str | None = None
    fused_candidates: int = Field(ge=0)
    rerank_status: Literal["not_configured", "applied", "fallback", "skipped"]
    returned_hits: int = Field(ge=0)
    truncated_hits: int = Field(default=0, ge=0)
    duration_ms: float = Field(ge=0)
    stage_duration_ms: dict[str, float] = Field(max_length=12)


class KnowledgeQueryInspectResponse(BaseModel):
    hits: list[KnowledgeQueryHitResponse]
    trace: KnowledgeRetrievalTraceResponse
    graph: KnowledgeGraphQueryResultResponse | None = None


KnowledgeEvaluationId = Annotated[str, Field(min_length=1, max_length=36)]


class KnowledgeGraphEvaluationExpectation(BaseModel):
    entity_names: list[str] = Field(default_factory=list, max_length=32)
    predicates: list[str] = Field(default_factory=list, max_length=32)
    path_entity_names: list[str] = Field(default_factory=list, max_length=16)
    path_predicates: list[str] = Field(default_factory=list, max_length=15)


class KnowledgeGraphEvaluationMetrics(BaseModel):
    entity_precision: float = Field(default=0, ge=0, le=1)
    entity_recall: float = Field(default=0, ge=0, le=1)
    claim_precision: float = Field(default=0, ge=0, le=1)
    claim_recall: float = Field(default=0, ge=0, le=1)
    path_exact_match: int = Field(default=0, ge=0, le=1)
    path_edge_accuracy: float = Field(default=0, ge=0, le=1)
    citation_coverage: float = Field(default=0, ge=0, le=1)


class KnowledgeEvaluationCaseCreateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    expected_document_ids: list[KnowledgeEvaluationId] = Field(
        min_length=1,
        max_length=20,
    )
    graph_expectation: KnowledgeGraphEvaluationExpectation | None = None


class KnowledgeEvaluationCaseResponse(BaseModel):
    id: str
    workspace_id: str
    knowledge_base_id: str
    question: str
    expected_document_ids: list[str]
    graph_expectation: KnowledgeGraphEvaluationExpectation | None = None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class KnowledgeEvaluationRunRequest(BaseModel):
    case_ids: list[KnowledgeEvaluationId] = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)
    search_mode: Literal["embedding", "keywords", "blend"] = "blend"
    similarity: float | None = Field(default=None, ge=0, le=1)
    include_references: bool = True
    graph_mode: Literal["off", "auto", "path", "neighborhood"] = "auto"
    max_hops: int = Field(default=6, ge=1, le=8)


class KnowledgeEvaluationResultResponse(BaseModel):
    id: str
    case_id: str
    question: str
    returned_document_ids: list[str]
    returned_chunk_ids: list[str]
    hit_at_k: int
    recall_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float
    latency_ms: float
    trace: dict[str, Any]
    graph_metrics: KnowledgeGraphEvaluationMetrics | None = None
    error: str | None
    created_at: datetime


class KnowledgeEvaluationSummaryResponse(BaseModel):
    task: KnowledgeTaskResponse
    count: int
    failed_count: int
    mean_hit_at_k: float
    mean_recall_at_k: float
    mean_reciprocal_rank: float
    mean_ndcg_at_k: float
    p50_latency_ms: float
    p95_latency_ms: float
    results: list[KnowledgeEvaluationResultResponse]
