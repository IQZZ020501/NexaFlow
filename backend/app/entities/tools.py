import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.infrastructure.model_utils import new_id, utc_now


MAX_PYTHON_TOOL_CODE_BYTES = 8 * 1024
MAX_TOOL_SCHEMA_BYTES = 16 * 1024
MAX_TOOL_SCHEMA_DEPTH = 8
MAX_TOOL_SCHEMA_PROPERTIES = 64
MAX_TOOL_ARRAY_ITEMS = 100
MAX_TOOL_STRING_LENGTH = 8 * 1024


@dataclass(frozen=True)
class ToolRef:
    tool_id: str
    version_id: str

    def __post_init__(self) -> None:
        if not self.tool_id.strip() or not self.version_id.strip():
            raise ValueError("Tool references require tool and version IDs.")


ToolKind = Literal["builtin", "python", "mcp"]
ToolApproval = Literal["auto", "each_call", "disabled"]
ToolEffect = Literal["pure", "external_read", "external_write", "unknown"]


@dataclass(frozen=True)
class ToolSnapshot:
    schema_version: int
    tool_id: str
    version_id: str
    source_id: str
    kind: ToolKind
    function_name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    definition_hash: str
    approval: ToolApproval
    effect: ToolEffect
    allowed_access_sources: tuple[str, ...]
    workflow_callable: bool
    parallel_safe: bool
    execution_spec: dict[str, Any]

    def __post_init__(self) -> None:
        ToolRef(tool_id=self.tool_id, version_id=self.version_id)


ToolGrant = Literal["view", "use"]


@dataclass(frozen=True)
class ToolAccess:
    can_view: bool
    can_use: bool
    can_manage: bool


def effective_tool_access(
    *,
    is_owner: bool,
    is_workspace_admin: bool,
    grant: ToolGrant | None,
) -> ToolAccess:
    if is_owner or is_workspace_admin:
        return ToolAccess(can_view=True, can_use=True, can_manage=True)
    can_use = grant == "use"
    return ToolAccess(
        can_view=can_use or grant == "view",
        can_use=can_use,
        can_manage=False,
    )


def validate_tool_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a closed, bounded copy of a Python Tool JSON Schema."""

    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("Tool schemas must describe an object.")

    def encoded_size(value: dict[str, Any]) -> int:
        try:
            payload = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Tool schema must be JSON serializable.") from exc
        return len(payload.encode("utf-8"))

    if encoded_size(schema) > MAX_TOOL_SCHEMA_BYTES:
        raise ValueError("Tool schema is too large.")

    def contains_reference(value: Any) -> bool:
        if isinstance(value, dict):
            if "$ref" in value or "$dynamicRef" in value:
                return True
            return any(contains_reference(child) for child in value.values())
        if isinstance(value, list):
            return any(contains_reference(child) for child in value)
        return False

    if contains_reference(schema):
        raise ValueError("Tool schemas cannot contain references.")

    restricted = deepcopy(schema)
    property_count = 0

    def schema_types(node: dict[str, Any]) -> set[str]:
        value = node.get("type")
        if isinstance(value, str):
            return {value}
        if (
            isinstance(value, list)
            and value
            and all(isinstance(item, str) for item in value)
        ):
            types = set(value)
            if len(types) == len(value) and len(types - {"null"}) == 1:
                return types
        raise ValueError("Tool schema nodes require one explicit JSON type.")

    def require_bounded_integer(
        node: dict[str, Any],
        keyword: str,
        maximum: int,
    ) -> None:
        value = node.get(keyword)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value > maximum
        ):
            raise ValueError(f"Tool schema {keyword} must be between 0 and {maximum}.")

    def restrict_node(node: dict[str, Any], depth: int) -> None:
        nonlocal property_count
        if depth > MAX_TOOL_SCHEMA_DEPTH:
            raise ValueError("Tool schema is too deeply nested.")
        if any(
            keyword in node
            for keyword in (
                "patternProperties",
                "unevaluatedProperties",
                "dependentSchemas",
                "propertyNames",
                "allOf",
                "anyOf",
                "oneOf",
                "not",
                "if",
                "then",
                "else",
                "prefixItems",
                "contains",
            )
        ):
            raise ValueError("Tool schema uses an unsupported composition keyword.")

        types = schema_types(node)
        if "object" in types:
            if node.get("additionalProperties", False) is not False:
                raise ValueError("Tool schemas cannot allow additional properties.")
            node["additionalProperties"] = False
            properties = node.get("properties", {})
            if not isinstance(properties, dict):
                raise ValueError("Tool schema properties must be an object.")
            property_count += len(properties)
            if property_count > MAX_TOOL_SCHEMA_PROPERTIES:
                raise ValueError("Tool schema has too many properties.")
            for child in properties.values():
                if not isinstance(child, dict):
                    raise ValueError("Tool schema properties must contain schemas.")
                restrict_node(child, depth + 1)
        if "array" in types:
            require_bounded_integer(node, "maxItems", MAX_TOOL_ARRAY_ITEMS)
            items = node.get("items")
            if not isinstance(items, dict):
                raise ValueError("Tool array schemas require one item schema.")
            restrict_node(items, depth + 1)
        if "string" in types:
            require_bounded_integer(node, "maxLength", MAX_TOOL_STRING_LENGTH)

    restrict_node(restricted, 1)
    try:
        Draft202012Validator.check_schema(restricted)
    except SchemaError as exc:
        raise ValueError("Tool schema is invalid.") from exc
    if encoded_size(restricted) > MAX_TOOL_SCHEMA_BYTES:
        raise ValueError("Tool schema is too large.")
    return restricted


def validate_python_tool_code(code: str) -> str:
    if len(code.encode("utf-8")) > MAX_PYTHON_TOOL_CODE_BYTES:
        raise ValueError("Python Tool code is too large.")
    return code


@dataclass
class McpServer:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    name: str = ""
    transport: str = "streamable_http"
    url: str | None = None
    stdio_command: str | None = None
    stdio_config_ciphertext: str | None = None
    bearer_token_ciphertext: str | None = None
    bearer_token_hint: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    status: str = "active"
    last_error: str | None = None
    created_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class McpToolPolicy:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    mcp_server_id: str = ""
    tool_name: str = ""
    definition_hash: str = ""
    mode: str = "approval_required"
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
