from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=6, max_length=255)
    current_password: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("new_password")
    @classmethod
    def require_uppercase(cls, value: str) -> str:
        if not any(character.isupper() for character in value):
            raise ValueError("Password must contain at least one uppercase letter.")
        return value


class UserWorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    is_default: bool
    role: str


class UserTeamResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    slug: str
    is_default: bool
    role: str


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    name: str
    is_global_admin: bool
    must_change_password: bool
    is_active: bool
    created_at: datetime
    workspaces: list[UserWorkspaceResponse] = Field(default_factory=list)
    teams: list[UserTeamResponse] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=80)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_global_admin: bool | None = None
    is_active: bool | None = None


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=120)
    is_global_admin: bool = False
    workspace_id: str | None = None
    team_ids: list[str] = Field(default_factory=list)


class UserPasswordResetResponse(BaseModel):
    user: UserResponse
    initial_password: str


class MembershipResponse(BaseModel):
    workspace_id: str
    role: str


class MeResponse(BaseModel):
    user: UserResponse
    memberships: list[MembershipResponse]
