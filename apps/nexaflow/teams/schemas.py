from pydantic import BaseModel, Field


class TeamResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    slug: str
    status: str
    is_default: bool


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=80)


class TeamUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=80)
    status: str | None = Field(default=None, max_length=20)
