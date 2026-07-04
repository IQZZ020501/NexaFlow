from pydantic import BaseModel, Field

from nexaflow.identity.schemas import UserResponse


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    is_default: bool


class WorkspaceAdminRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=120)


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=80)
    admin: WorkspaceAdminRequest


class WorkspaceCreateResponse(BaseModel):
    workspace: WorkspaceResponse
    admin_user: UserResponse
    admin_created: bool
    admin_initial_password: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=80)
    status: str | None = Field(default=None, max_length=20)
