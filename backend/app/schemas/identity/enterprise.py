from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.time import AppDateTime

EnterpriseProvider = Literal["feishu", "dingtalk", "wecom"]


class EnterpriseConnectionUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    client_id: str | None = Field(default=None, min_length=1, max_length=255)
    client_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=255)
    agent_id: str | None = Field(default=None, max_length=255)
    enabled: bool = True


class EnterpriseConnectionResponse(BaseModel):
    id: str
    workspace_id: str
    provider: EnterpriseProvider
    name: str
    client_id: str
    tenant_id: str
    agent_id: str | None
    enabled: bool
    has_client_secret: bool
    client_secret_hint: str | None
    callback_url: str
    login_url: str
    updated_at: AppDateTime


class PublicEnterpriseConnectionResponse(BaseModel):
    id: str
    provider: EnterpriseProvider
    name: str
    start_url: str


class PublicEnterpriseConnectionsResponse(BaseModel):
    workspace_id: str | None = None
    workspace_name: str | None = None
    connections: list[PublicEnterpriseConnectionResponse]


class EnterpriseIdentityBindingRequest(BaseModel):
    user_id: str | None = Field(default=None, max_length=36)


class EnterpriseIdentityResponse(BaseModel):
    id: str
    connection_id: str
    provider: EnterpriseProvider
    user_id: str | None
    username: str | None
    user_name: str | None
    subject_id: str
    display_name: str
    email: str | None
    status: str
    last_login_at: AppDateTime | None
    created_at: AppDateTime
