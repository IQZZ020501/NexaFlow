from datetime import datetime

from pydantic import BaseModel, Field

from nexaflow.identity.schemas import UserResponse


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


class KnowledgeDocumentResponse(BaseModel):
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
