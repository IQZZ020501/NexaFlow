"""Public chat project contracts. Project identity never grants execution rights."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ChatProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default="", max_length=12000)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be empty.")
        return value.strip()


class ChatProjectUpdate(ChatProjectCreate):
    archived: bool = False


class ChatProjectResponse(BaseModel):
    id: str
    name: str
    instructions: str
    archived: bool
    created_at: datetime
    updated_at: datetime


class ChatProjectListResponse(BaseModel):
    items: list[ChatProjectResponse]


class ChatProjectFileResponse(BaseModel):
    id: str
    path: str
    size_bytes: int
    content_hash: str


class ChatProjectFileListResponse(BaseModel):
    items: list[ChatProjectFileResponse]


class ChatConversationMove(BaseModel):
    project_id: str | None = Field(default=None, min_length=1, max_length=36)


class ChatConversationResponse(BaseModel):
    conversation_id: str
    project_id: str | None


class ChatProjectArtifactRequest(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=36)
