from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    name: str
    revision: int
    created_at: datetime
    updated_at: datetime


class ProjectFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    path: str
    role: Literal["source", "work"]
    revision: int
    previous_version_id: str | None
    deleted: bool
    content_hash: str
    size_bytes: int
    run_id: str | None
    created_at: datetime


class ProjectFileDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=512)
    expected_version_id: str = Field(min_length=1, max_length=36)


class ProjectFileRenameRequest(ProjectFileDeleteRequest):
    new_path: str = Field(min_length=1, max_length=512)
