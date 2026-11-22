from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.time import AppDateTime


class McpOAuthConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorization_endpoint: str = Field(min_length=1, max_length=2048)
    token_endpoint: str = Field(min_length=1, max_length=2048)
    revocation_endpoint: str = Field(min_length=1, max_length=2048)
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=8000)
    client_auth_method: Literal["none", "client_secret_basic", "client_secret_post"] = (
        "none"
    )
    scopes: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def scopes_are_bounded(self):
        if any(
            not scope
            or len(scope) > 128
            or any(ord(c) < 33 or ord(c) > 126 for c in scope)
            for scope in self.scopes
        ):
            raise ValueError("OAuth scopes must be bounded printable scope tokens.")
        if self.client_auth_method != "none" and not self.client_secret:
            raise ValueError("OAuth client authentication requires a client secret.")
        return self


class McpOAuthCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(min_length=32, max_length=128)
    code: str = Field(min_length=1, max_length=8000)


class McpOAuthStatus(BaseModel):
    status: Literal[
        "disconnected", "connected", "refreshing", "reauthorization_required"
    ]
    expires_at: AppDateTime | None = None
    configuration: dict


class McpOAuthAuthorization(BaseModel):
    authorization_url: str
    redirect_uri: str
