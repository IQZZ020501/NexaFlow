from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

IntegrationProvider = Literal["dida", "feishu", "tencent_meeting"]
_Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]


class IntegrationResponse(BaseModel):
    provider: IntegrationProvider
    status: Literal["disconnected", "connected", "reauthorization_required"]
    configured: bool
    expires_at: datetime | None
    source_id: str | None


class IntegrationApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: _Text
    client_secret: (
        Annotated[str, StringConstraints(min_length=1, max_length=8000)] | None
    ) = None
    scopes: list[_Text] = Field(default_factory=list, max_length=32)


class IntegrationApplicationResponse(BaseModel):
    client_id: str
    has_client_secret: bool
    scopes: list[str]
    redirect_uri: str


class IntegrationAuthorizeResponse(BaseModel):
    authorization_url: str
    state: str
    mode: Literal["redirect", "device"]
    poll_seconds: int = 5


class IntegrationCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    code: Annotated[str, StringConstraints(min_length=1, max_length=4096)] | None = None
