from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.time import AppDateTime

ResourceFolderType = Literal["knowledge", "application", "model", "tool"]


class ResourceFolderResponse(BaseModel):
    id: str
    workspace_id: str
    resource_type: ResourceFolderType
    parent_id: str | None
    name: str
    created_by_user_id: str | None
    created_at: AppDateTime
    updated_at: AppDateTime


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


class ResourceFolderBatchMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: ResourceFolderType
    resource_ids: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(
        min_length=1,
        max_length=200,
    )
    folder_id: str | None = Field(default=None, max_length=36)
