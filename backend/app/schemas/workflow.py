from datetime import datetime
import re
from typing import Annotated, Any, Literal

from jinja2 import Environment, TemplateSyntaxError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.agent import AgentInteractionConfig
from app.schemas.tool import ToolRefSchema

JINJA_ENV = Environment()


WorkflowNodeType = Literal[
    "start",
    "end",
    "llm",
    "classifier",
    "knowledge",
    "reranker-node",
    "form-node",
    "document-extract-node",
    "condition",
    "reply-node",
    "template",
    "variable",
    "tool",
    "agent",
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
    nodes: list[WorkflowNode] = Field(min_length=1, max_length=200)
    edges: list[WorkflowEdge] = Field(max_length=500)
    viewport: WorkflowViewport = Field(default_factory=WorkflowViewport)


class StartNodeConfig(BaseModel):
    """Fixed start node: no configuration; exposes the run question and globals."""


class EndNodeConfig(BaseModel):
    outputs: dict[str, Any] = Field(default_factory=dict, max_length=50)


class LlmMcpServer(BaseModel):
    """MCP tool reference for the LLM node; must use a read-only policy."""

    server_id: str = Field(min_length=1, max_length=36)
    tool_name: str = Field(min_length=1, max_length=255)


class LlmModelSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning_content_enable: bool = False


class LlmNodeConfig(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    system_prompt: str = Field(default="", max_length=20000)
    model_id: str | None = Field(default=None, min_length=1, max_length=36)
    dialogue_number: int = Field(default=1, ge=0, le=20)
    dialogue_type: Literal["NODE", "WORKFLOW"] = "NODE"
    model_params_setting: dict[str, Any] = Field(default_factory=dict, max_length=20)
    model_setting: LlmModelSetting = Field(default_factory=LlmModelSetting)
    mcp_enable: bool = False
    mcp_servers: list[LlmMcpServer] = Field(default_factory=list, max_length=20)
    tools: list[ToolRefSchema] = Field(default_factory=list, max_length=20)
    is_result: bool = True

    @model_validator(mode="after")
    def validate_tools(self) -> "LlmNodeConfig":
        if len({item.tool_id for item in self.tools}) != len(self.tools):
            raise ValueError("LLM Tool references must be unique.")
        return self


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
    ] = Field(default_factory=list, max_length=50)
    query: Any
    limit: int = Field(default=3, ge=1, le=8)
    similarity: float = Field(default=0.6, ge=0, le=1)
    search_mode: Literal["embedding", "keywords", "blend"] = "embedding"
    max_paragraph_char_number: int = Field(default=5000, ge=1, le=20000)
    # 内部维护，发布时由资源校验反向解析；前端不手填
    source_dataset_id_list: list[
        Annotated[str, Field(min_length=1, max_length=36)]
    ] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_knowledge_bases(self) -> "KnowledgeNodeConfig":
        ids = self.resolved_knowledge_base_ids
        if not ids:
            raise ValueError("At least one knowledge base is required.")
        if len(ids) > 50:
            raise ValueError("At most 50 knowledge bases are allowed.")
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


class RerankerSetting(BaseModel):
    top_n: int = Field(default=3, ge=1, le=50)
    similarity: float = Field(default=0, ge=0, le=2)
    max_paragraph_char_number: int = Field(default=5000, ge=1, le=20000)


class RerankerNodeConfig(BaseModel):
    reranker_model_id: str = Field(min_length=1, max_length=36)
    question_reference_address: Any
    reranker_reference_list: list[Any] = Field(min_length=1, max_length=50)
    reranker_setting: RerankerSetting = Field(default_factory=RerankerSetting)


class FormField(BaseModel):
    variable: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    name: str = Field(min_length=1, max_length=120)
    type: Literal["input", "textarea", "select", "date", "number"] = "input"
    is_required: bool = False
    default_value: Any = None
    show_default_value: bool = False
    optionList: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_options(self) -> "FormField":
        if self.type == "select" and not self.optionList:
            raise ValueError("Select form fields require options.")
        return self


class FormNodeConfig(BaseModel):
    form_field_list: list[FormField] = Field(min_length=1, max_length=50)
    form_content_format: str = Field(min_length=1, max_length=20000)
    is_result: bool = True

    @model_validator(mode="after")
    def validate_form(self) -> "FormNodeConfig":
        variables = [item.variable for item in self.form_field_list]
        if len(variables) != len(set(variables)):
            raise ValueError("Form field variables must be unique.")
        if set(variables) & {"form_data", "result"}:
            raise ValueError("Form field variables use reserved output names.")
        if len(re.findall(r"{{\s*form\s*}}", self.form_content_format)) != 1:
            raise ValueError("Form content must contain one {{ form }} placeholder.")
        try:
            JINJA_ENV.parse(self.form_content_format)
        except TemplateSyntaxError as exc:
            raise ValueError(f"Invalid form template: {exc}") from exc
        return self


class DocumentExtractNodeConfig(BaseModel):
    document_list: Any


ConditionCompare = Literal[
    "is_null",
    "is_not_null",
    "contain",
    "not_contain",
    "eq",
    "ge",
    "gt",
    "le",
    "lt",
    "len_eq",
    "len_ge",
    "len_gt",
    "len_le",
    "len_lt",
    "is_true",
    "is_not_true",
    "not_eq",
]


class ConditionRule(BaseModel):
    field: tuple[
        Annotated[str, Field(min_length=1, max_length=80)],
        Annotated[str, Field(min_length=1, max_length=255)],
    ]
    compare: ConditionCompare
    value: str = Field(max_length=4000)


class ConditionBranch(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    type: Literal["IF", "ELSE IF", "ELSE"]
    condition: Literal["and", "or"]
    conditions: list[ConditionRule] = Field(max_length=20)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_legacy_type(cls, value: Any) -> Any:
        if isinstance(value, str) and re.fullmatch(r"ELSE IF [1-9][0-9]*", value):
            return "ELSE IF"
        return value


class ConditionNodeConfig(BaseModel):
    branch: list[ConditionBranch] = Field(min_length=1, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_condition(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "branch" in value:
            return value
        field = value.get("left")
        match = (
            re.fullmatch(
                r"{{\s*([A-Za-z0-9_-]+)\.([A-Za-z0-9_.-]+)\s*}}", field
            )
            if isinstance(field, str)
            else None
        )
        compares = {
            "equals": "eq",
            "not_equals": "not_eq",
            "contains": "contain",
            "not_contains": "not_contain",
            "greater_than": "gt",
            "greater_than_or_equal": "ge",
            "less_than": "lt",
            "less_than_or_equal": "le",
            "is_empty": "is_null",
            "is_not_empty": "is_not_null",
            "length_equals": "len_eq",
            "length_greater_than": "len_gt",
            "length_greater_than_or_equal": "len_ge",
            "length_less_than": "len_lt",
            "length_less_than_or_equal": "len_le",
            "is_true": "is_true",
            "is_false": "is_not_true",
        }
        compare = compares.get(str(value.get("operator")))
        if match is None or compare is None:
            return value
        return {
            "branch": [
                {
                    "id": "true",
                    "type": "IF",
                    "condition": "and",
                    "conditions": [
                        {
                            "field": [match.group(1), match.group(2)],
                            "compare": compare,
                            "value": str(
                                value.get("right")
                                if value.get("right") is not None
                                else ""
                            ),
                        }
                    ],
                },
                {
                    "id": "false",
                    "type": "ELSE",
                    "condition": "and",
                    "conditions": [],
                },
            ]
        }

    @model_validator(mode="after")
    def validate_branches(self) -> "ConditionNodeConfig":
        if len({item.id for item in self.branch}) != len(self.branch):
            raise ValueError("Condition branch ids must be unique.")
        for index, item in enumerate(self.branch):
            expected_type = "IF" if index == 0 else "ELSE IF"
            if item.type == "ELSE":
                if index != len(self.branch) - 1 or item.conditions:
                    raise ValueError("ELSE must be the final branch and have no conditions.")
                continue
            if item.type != expected_type or not item.conditions:
                raise ValueError(
                    "Condition branches must be ordered as IF followed by ELSE IF branches."
                )
        return self


class TemplateNodeConfig(BaseModel):
    template: str = Field(max_length=20000)


class ReplyNodeConfig(BaseModel):
    reply_type: Literal["custom", "referencing"]
    content: str = Field(default="", max_length=20000)
    fields: tuple[
        list[
            Annotated[
                str,
                Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$"),
            ]
        ],
        Annotated[str, Field(max_length=500)],
    ] | None = None
    is_result: bool = True

    @model_validator(mode="after")
    def validate_reply_source(self) -> "ReplyNodeConfig":
        if self.reply_type == "custom" and not self.content.strip():
            raise ValueError("Reply content is required for custom replies.")
        if self.reply_type == "custom":
            try:
                JINJA_ENV.parse(self.content)
            except TemplateSyntaxError as exc:
                raise ValueError(f"Invalid reply template: {exc}") from exc
        if self.reply_type == "referencing" and (
            self.fields is None or len(self.fields[0]) < 2
        ):
            raise ValueError("Reply fields must contain a reference path and description.")
        return self


class VariableNodeConfig(BaseModel):
    value: Any


class ToolNodeConfig(BaseModel):
    tool: ToolRefSchema
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=100)


class WorkflowAgentNodeConfig(BaseModel):
    agent_version_id: str = Field(min_length=1, max_length=36)
    input: Any


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
    question: str = Field(min_length=1, max_length=4000)
    source: Literal["draft", "published"] = "draft"
    version_number: int | None = Field(default=None, ge=1)
    file_ids: list[str] = Field(default_factory=list)


class WorkflowFormSubmitRequest(BaseModel):
    runtime_node_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    form_data: dict[str, Any] = Field(max_length=50)


class WorkflowPendingForm(BaseModel):
    runtime_node_id: str
    content: str
    fields: list[FormField]


class WorkflowNodeExecutionResponse(BaseModel):
    id: str
    run_id: str
    node_id: str
    node_type: WorkflowNodeType
    status: Literal[
        "running",
        "awaiting_input",
        "awaiting_child",
        "succeeded",
        "failed",
        "skipped",
    ]
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
    pending_form: WorkflowPendingForm | None = None


class WorkflowNodeExecutionListResponse(BaseModel):
    items: list[WorkflowNodeExecutionResponse]


class PublicWorkflowProfileResponse(BaseModel):
    id: str
    name: str
    description: str
    interaction_config: AgentInteractionConfig = Field(
        default_factory=AgentInteractionConfig
    )


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
    question: str = Field(min_length=1, max_length=4000)
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
    status: Literal[
        "running",
        "awaiting_input",
        "awaiting_child",
        "succeeded",
        "failed",
        "skipped",
    ]
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
    pending_form: WorkflowPendingForm | None = None


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
