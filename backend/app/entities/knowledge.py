from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.infrastructure.model_utils import new_id, utc_now

DOCUMENT_STAGED_META_KEY = "staged"

VISIBLE_DOCUMENT_STATUSES = (
    "uploaded",
    "parse_queued",
    "parsing",
    "parsed",
    "parse_failed",
    "index_queued",
    "indexing",
    "indexed",
    "index_failed",
)

# Document lifecycle statuses (business state machine).
DOCUMENT_DELETED_STATUS = "deleted"
DOCUMENT_PARSE_QUEUED_STATUS = "parse_queued"
DOCUMENT_PARSING_STATUS = "parsing"
DOCUMENT_PARSED_STATUS = "parsed"
DOCUMENT_PARSE_FAILED_STATUS = "parse_failed"
DOCUMENT_INDEX_QUEUED_STATUS = "index_queued"
DOCUMENT_INDEXING_STATUS = "indexing"
DOCUMENT_INDEXED_STATUS = "indexed"
DOCUMENT_INDEX_FAILED_STATUS = "index_failed"

# Chunk statuses.
CHUNK_PREVIEW_STATUS = "preview"
CHUNK_INDEXED_STATUS = "indexed"
CHUNK_INDEX_FAILED_STATUS = "index_failed"

# Knowledge task types and statuses.
TASK_PARSE = "parse"
TASK_INDEX = "index"
TASK_REBUILD_INDEX = "rebuild_index"
TASK_EVALUATE = "evaluate"
TASK_GRAPH_SYNC = "graph_sync"
TASK_GRAPH_REBUILD = "graph_rebuild"
TASK_QUEUED_STATUS = "queued"
TASK_RUNNING_STATUS = "running"
TASK_SUCCEEDED_STATUS = "succeeded"
TASK_FAILED_STATUS = "failed"


@dataclass
class KnowledgeBase:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    name: str = ""
    description: str = ""
    status: str = "active"
    embedding_model_id: str | None = None
    reranker_model_id: str | None = None
    graph_enabled: bool = False
    active_graph_schema_id: str | None = None
    active_graph_revision_id: str | None = None
    graph_extraction_model_id: str | None = None
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeAttachment:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    object_key: str = ""
    status: str = "available"
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeDocument:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    attachment_id: str | None = None
    filename: str = ""
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    storage_path: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    status: str = "uploaded"
    is_active: bool = True
    last_error: str | None = None
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeAsset:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    document_id: str = ""
    asset_index: int = 0
    kind: str = "image"
    filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    object_key: str = ""
    alt_text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeDocumentParentChunk:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    document_id: str = ""
    parent_index: int = 0
    title: str = ""
    content: str = ""
    char_count: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeDocumentChunk:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    document_id: str = ""
    parent_id: str | None = None
    chunk_index: int = 0
    start_offset: int | None = None
    end_offset: int | None = None
    content: str = ""
    kind: str = "document"
    search_text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    char_count: int = 0
    token_count: int = 0
    vector_id: str | None = None
    status: str = "preview"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeDocumentReference:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    source_document_id: str = ""
    source_chunk_id: str = ""
    target_document_id: str | None = None
    target_parent_id: str | None = None
    target_label: str = ""
    target_section: str = ""
    reference_type: str = "text"
    source_ordinal: int = 0
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeChunkAsset:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    document_id: str = ""
    chunk_id: str = ""
    asset_id: str = ""
    asset_index: int = 0
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeTask:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    document_id: str | None = None
    task_type: str = ""
    status: str = "queued"
    attempts: int = 0
    max_attempts: int = 3
    total_items: int = 0
    processed_items: int = 0
    options: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    created_by_user_id: str = ""
    started_at: datetime | None = None
    lease_expires_at: datetime | None = None
    worker_task_id: str | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeEvaluationCase:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    question: str = ""
    answer_points: list[str] = field(default_factory=list)
    graph_expectation: dict[str, Any] = field(default_factory=dict)
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeEvaluationExpectation:
    workspace_id: str = ""
    knowledge_base_id: str = ""
    case_id: str = ""
    document_id: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeEvaluationResult:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    task_id: str = ""
    case_id: str = ""
    returned_document_ids: list[str] = field(default_factory=list)
    returned_chunk_ids: list[str] = field(default_factory=list)
    hit_at_k: int = 0
    recall_at_k: float = 0.0
    reciprocal_rank: float = 0.0
    ndcg_at_k: float = 0.0
    latency_ms: float = 0.0
    trace: dict[str, Any] = field(default_factory=dict)
    graph_metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class KnowledgeStorageCleanup:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    knowledge_base_id: str = ""
    attempts: int = 0
    last_error: str | None = None
    next_attempt_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
