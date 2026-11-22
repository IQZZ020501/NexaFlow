from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.time import AppDateTime

IntegrationProvider = Literal["dida", "feishu", "tencent_meeting"]


class IntegrationAuthorizeResponse(BaseModel):
    authorization_url: str
    state: str
    mode: Literal["redirect", "device"]
    poll_seconds: int = 5
    phase: Literal["application", "login"] | None = None
    expires_in: int = 300


class IntegrationResponse(BaseModel):
    provider: IntegrationProvider
    status: Literal["disconnected", "connected", "reauthorization_required"]
    configured: bool
    expires_at: AppDateTime | None
    source_id: str | None
    authorization: IntegrationAuthorizeResponse | None = None


class IntegrationCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    code: Annotated[str, StringConstraints(min_length=1, max_length=4096)] | None = None
