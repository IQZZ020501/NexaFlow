from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.user import UserResponse


class KnowledgeBaseResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    status: str
    embedding_model_id: str | None
    reranker_model_id: str | None
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


class KnowledgeDocumentCreateRequest(BaseModel):
    attachment_ids: list[str] = Field(min_length=1, max_length=30)
    staged: bool = True


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


class KnowledgeQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)
    search_mode: Literal["embedding", "keywords", "blend"] = "blend"
    # 相似度阈值（余弦距离，0–2，保留距离不超过该值的命中）
    similarity: float | None = Field(default=None, ge=0, le=2)
    include_references: bool = False


class KnowledgeQueryHitResponse(BaseModel):
    chunk_id: str
    document_id: str
    document_filename: str
    parent_id: str | None = None
    parent_title: str | None = None
    parent_index: int | None = None
    chunk_index: int
    content: str
    distance: float | None = None
    kind: Literal["document", "qa"] = "document"
    question: str | None = None
    source: str | None = None
    sources: list[str] = Field(default_factory=list, max_length=3)
    reference_hops: int = Field(default=0, ge=0, le=1)
    rerank_score: float | None = None


class KnowledgeRetrievalTraceResponse(BaseModel):
    trace_id: str
    search_mode: Literal["embedding", "keywords", "blend"]
    limit: int = Field(ge=1, le=20)
    max_distance: float | None = Field(default=None, ge=0, le=2)
    vector_candidates: int = Field(ge=0)
    keyword_candidates: int = Field(ge=0)
    reference_candidates: int = Field(ge=0)
    fused_candidates: int = Field(ge=0)
    rerank_status: Literal["not_configured", "applied", "fallback", "skipped"]
    returned_hits: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    stage_duration_ms: dict[str, float] = Field(max_length=8)


class KnowledgeQueryInspectResponse(BaseModel):
    hits: list[KnowledgeQueryHitResponse]
    trace: KnowledgeRetrievalTraceResponse
