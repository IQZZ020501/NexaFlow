from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.agent import AgentInteractionConfig


WorkflowNodeType = Literal[
    "start",
    "end",
    "llm",
    "classifier",
    "knowledge",
    "condition",
    "template",
    "variable",
    "mcp",
    "code",
]


class WorkflowPosition(BaseModel):
    x: float
    y: float


class WorkflowNodeData(BaseModel):
    type: WorkflowNodeType
    title: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    type: Literal["workflow"] = "workflow"
    position: WorkflowPosition
    data: WorkflowNodeData


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    source_handle: str | None = Field(
        default=None,
        alias="sourceHandle",
        min_length=1,
        max_length=80,
    )
    target_handle: str | None = Field(
        default=None,
        alias="targetHandle",
        min_length=1,
        max_length=80,
    )


class WorkflowViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = Field(default=1, ge=0.1, le=4)


class WorkflowGraph(BaseModel):
    nodes: list[WorkflowNode] = Field(min_length=2, max_length=200)
    edges: list[WorkflowEdge] = Field(min_length=1, max_length=500)
    viewport: WorkflowViewport = Field(default_factory=WorkflowViewport)


class WorkflowInputField(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    label: str = Field(default="", max_length=120)
    type: Literal["string", "number", "boolean", "object", "array"] = "string"
    control: Literal["input", "select", "date"] = "input"
    required: bool = True
    default: Any = None
    options: list[str] = Field(default_factory=list, max_length=50)
    assignment_method: Literal["user_input", "api_input"] = "user_input"

    @model_validator(mode="after")
    def validate_control(self) -> "WorkflowInputField":
        if self.control == "select" and not self.options:
            raise ValueError("Select inputs require at least one option.")
        if self.control == "select" and self.type != "string":
            raise ValueError("Select inputs must use the string value type.")
        if any(not option.strip() or len(option) > 120 for option in self.options):
            raise ValueError("Input options must contain 1 to 120 characters.")
        if len(self.options) != len(set(self.options)):
            raise ValueError("Input options must be unique.")
        if self.control == "date" and self.type != "string":
            raise ValueError("Date inputs must use the string value type.")
        if self.default is not None:
            self.validate_control_value(self.default)
        return self

    def validate_control_value(self, value: Any) -> None:
        if self.control == "select" and value not in self.options:
            raise ValueError(f"Workflow input {self.name} must use a configured option.")
        if self.control == "date":
            try:
                date.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Workflow input {self.name} must use an ISO date."
                ) from exc


class StartNodeConfig(BaseModel):
    inputs: list[WorkflowInputField] = Field(default_factory=list, max_length=50)


class EndNodeConfig(BaseModel):
    outputs: dict[str, Any] = Field(default_factory=dict, max_length=50)


class LlmNodeConfig(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    system_prompt: str = Field(default="", max_length=20000)
    model_id: str | None = Field(default=None, min_length=1, max_length=36)


class ClassifierClass(BaseModel):
    handle: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class ClassifierNodeConfig(BaseModel):
    input: Any
    classes: list[ClassifierClass] = Field(min_length=1, max_length=20)
    default_handle: str = Field(
        default="default",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    model_id: str | None = Field(default=None, min_length=1, max_length=36)


class KnowledgeNodeConfig(BaseModel):
    knowledge_base_id: str | None = Field(default=None, min_length=1, max_length=36)
    knowledge_base_ids: list[
        Annotated[str, Field(min_length=1, max_length=36)]
    ] = Field(default_factory=list, max_length=10)
    query: Any
    limit: int = Field(default=3, ge=1, le=8)

    @model_validator(mode="after")
    def validate_knowledge_bases(self) -> "KnowledgeNodeConfig":
        ids = self.resolved_knowledge_base_ids
        if not ids:
            raise ValueError("At least one knowledge base is required.")
        if len(ids) > 10:
            raise ValueError("At most 10 knowledge bases are allowed.")
        return self

    @property
    def resolved_knowledge_base_ids(self) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    *([self.knowledge_base_id] if self.knowledge_base_id else []),
                    *self.knowledge_base_ids,
                ]
            )
        )


class ConditionNodeConfig(BaseModel):
    left: Any
    operator: Literal[
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "is_empty",
        "is_not_empty",
        "length_equals",
        "length_greater_than",
        "length_greater_than_or_equal",
        "length_less_than",
        "length_less_than_or_equal",
        "is_true",
        "is_false",
    ]
    right: Any = None


class TemplateNodeConfig(BaseModel):
    template: str = Field(max_length=20000)


class VariableNodeConfig(BaseModel):
    value: Any


class McpNodeConfig(BaseModel):
    server_id: str = Field(min_length=1, max_length=36)
    tool_name: str = Field(min_length=1, max_length=255)
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=100)


class CodeNodeConfig(BaseModel):
    code: str = Field(min_length=1, max_length=8000)
    inputs: dict[str, Any] = Field(default_factory=dict, max_length=100)


class WorkflowDefinitionResponse(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    revision: int
    graph: WorkflowGraph
    graph_hash: str
    updated_by_user_id: str
    created_at: datetime
    updated_at: datetime


class WorkflowDefinitionUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    graph: WorkflowGraph


class WorkflowVersionRestoreRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class WorkflowValidationResponse(BaseModel):
    valid: Literal[True] = True
    graph_hash: str


class WorkflowVersionResponse(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    definition_id: str
    definition_revision: int
    version_number: int
    default_model_id: str
    graph: WorkflowGraph
    graph_hash: str
    published_by_user_id: str
    created_at: datetime


class WorkflowVersionListResponse(BaseModel):
    items: list[WorkflowVersionResponse]


class WorkflowValidationRequest(BaseModel):
    graph: WorkflowGraph


class WorkflowRunCreateRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict, max_length=100)
    source: Literal["draft", "published"] = "draft"
    version_number: int | None = Field(default=None, ge=1)


class WorkflowNodeExecutionResponse(BaseModel):
    id: str
    run_id: str
    node_id: str
    node_type: WorkflowNodeType
    status: Literal["running", "succeeded", "failed", "skipped"]
    sequence: int
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    model_usage: dict[str, Any]
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


class WorkflowRunResponse(BaseModel):
    id: str
    conversation_id: str
    workspace_id: str
    agent_id: str
    requested_by_user_id: str | None
    status: str
    source: Literal["draft", "published"]
    definition_revision: int
    version_number: int | None
    graph_hash: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    max_steps: int
    max_model_tokens: int
    step_count: int
    token_usage: int
    last_error: str | None
    trace_id: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkflowNodeExecutionListResponse(BaseModel):
    items: list[WorkflowNodeExecutionResponse]


class PublicWorkflowInputFieldResponse(BaseModel):
    name: str
    label: str = ""
    type: Literal["string", "number", "boolean", "object", "array"]
    control: Literal["input", "select", "date"] = "input"
    required: bool
    default: Any = None
    options: list[str] = Field(default_factory=list)
    assignment_method: Literal["user_input", "api_input"] = "user_input"


class PublicWorkflowProfileResponse(BaseModel):
    id: str
    name: str
    description: str
    interaction_config: AgentInteractionConfig = Field(
        default_factory=AgentInteractionConfig
    )
    inputs: list[PublicWorkflowInputFieldResponse] = Field(default_factory=list)


class PublicWorkflowConversationResponse(BaseModel):
    conversation_id: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    status: str
    run_count: int
    created_at: datetime
    updated_at: datetime


class PublicWorkflowConversationListResponse(BaseModel):
    items: list[PublicWorkflowConversationResponse]


class ExternalWorkflowRunCreateRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict, max_length=100)
    file_ids: list[str] = Field(default_factory=list)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=36)


class WorkflowUploadResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    category: Literal["document", "image", "audio"]


class ExternalWorkflowProgressEventResponse(BaseModel):
    id: str
    node_id: str
    node_type: WorkflowNodeType
    status: Literal["running", "succeeded", "failed", "skipped"]
    error: str | None = None
    duration_ms: int | None = None


class ExternalWorkflowRunResponse(BaseModel):
    id: str
    conversation_id: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    status: str
    error: str | None
    progress: list[ExternalWorkflowProgressEventResponse] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class ExternalWorkflowRunListResponse(BaseModel):
    items: list[ExternalWorkflowRunResponse]
    total: int
    offset: int
    limit: int


class WorkflowApiDocumentationResponse(BaseModel):
    workflow_id: str
    workflow_name: str
    base_path: str
    interaction_config: AgentInteractionConfig = Field(
        default_factory=AgentInteractionConfig
    )
    inputs: list[PublicWorkflowInputFieldResponse] = Field(default_factory=list)
