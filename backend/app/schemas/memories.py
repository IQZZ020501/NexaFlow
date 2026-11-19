from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MemoryCategory = Literal["preference", "background", "goal", "project"]


class MemoryPreferencesRequest(BaseModel):
    enabled: bool
    automatic: bool


class MemoryWriteRequest(BaseModel):
    category: MemoryCategory = "preference"
    key: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=600)
    project_id: str = Field(default="", max_length=36)
    expires_at: datetime | None = None

    @field_validator("key", "content")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Memory must not be blank.")
        return value.strip()

    @model_validator(mode="after")
    def validate_scope(self):
        if self.category == "project" and not self.project_id:
            raise ValueError("Project memory requires a project.")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("Memory expiry must include a time zone.")
        return self


class MemoryResponse(MemoryWriteRequest):
    id: str
    origin: Literal["manual", "explicit", "automatic"]
    source_run_id: str | None
    source_quote: str
    source_conversation_id: str | None = None
    source_agent_id: str | None = None
    updated_at: datetime


class MemoryProfileResponse(MemoryPreferencesRequest):
    items: list[MemoryResponse]


class MemoryProjectResponse(BaseModel):
    id: str
    name: str
    archived: bool
    agent_id: str


class MemoryProjectListResponse(BaseModel):
    items: list[MemoryProjectResponse]
