from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ModelProviderCatalogResponse(BaseModel):
    provider: str
    name: str
    provider_type: str
    icon: str = ""
    model_types: list[str]
    default_api_base: str


class BaseModelOptionResponse(BaseModel):
    name: str
    desc: str = ""
    model_type: str


class ModelCredentialFieldResponse(BaseModel):
    field: str
    label: str
    input_type: str
    required: bool = True
    default_value: Any = None


class RegisteredModelResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    provider: str
    provider_type: str
    model_type: str
    model_name: str
    status: str
    credential: dict[str, Any]
    api_base: str
    has_api_key: bool
    api_key_hint: str | None
    meta: dict[str, Any]
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class RegisteredModelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=80)
    provider_type: str = Field(default="openai_compatible", min_length=1, max_length=40)
    model_type: str = Field(default="LLM", min_length=1, max_length=20)
    model_name: str = Field(min_length=1, max_length=160)
    credential: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class RegisteredModelUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    provider_type: str | None = Field(default=None, min_length=1, max_length=40)
    model_type: str | None = Field(default=None, min_length=1, max_length=20)
    model_name: str | None = Field(default=None, min_length=1, max_length=160)
    credential: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    status: str | None = Field(default=None, min_length=1, max_length=20)
