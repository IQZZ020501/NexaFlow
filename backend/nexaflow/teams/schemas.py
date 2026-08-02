from pydantic import BaseModel, Field


class TeamResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    status: str
    is_default: bool


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class TeamUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=20)
