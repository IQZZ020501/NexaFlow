from pydantic import BaseModel, ConfigDict, Field, model_validator


class McpTaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status_tool: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$"
    )
    result_tool: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$"
    )
    cancel_tool: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$"
    )
    poll_seconds: int = Field(default=3, ge=1, le=30)

    @model_validator(mode="after")
    def distinct_operations(self):
        if len({self.status_tool, self.result_tool, self.cancel_tool}) != 3:
            raise ValueError("Long-task control tools must be distinct.")
        return self


class McpTaskConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contracts: dict[str, McpTaskContract] = Field(default_factory=dict, max_length=16)


class McpTaskConfigurationResponse(McpTaskConfiguration):
    tools: list[str]
