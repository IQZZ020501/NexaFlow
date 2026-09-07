from pydantic import BaseModel, ConfigDict, Field


class ArtifactDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=4096)
