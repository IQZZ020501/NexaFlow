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
    char_count: int = 0
    token_count: int = 0
    vector_id: str | None = None
    status: str = "preview"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


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
