from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ResourceFolderType = Literal["knowledge", "application", "tool"]


class ResourceFolderResponse(BaseModel):
    id: str
    workspace_id: str
    resource_type: ResourceFolderType
    parent_id: str | None
    name: str
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime


class ResourceFolderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    resource_type: ResourceFolderType
    parent_id: str | None = Field(default=None, max_length=36)


class ResourceFolderUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: str | None = Field(default=None, max_length=36)


class ResourceFolderMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: ResourceFolderType
    resource_id: str = Field(min_length=1, max_length=36)
    folder_id: str | None = Field(default=None, max_length=36)
