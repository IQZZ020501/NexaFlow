import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
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


class FrozenJsonDict(dict[str, Any]):
    """A JSON-serializable mapping that rejects in-place mutation."""

    def __new__(cls, values: Any = ()) -> "FrozenJsonDict":
        instance = super().__new__(cls)
        dict.update(instance, values)
        return instance

    def __init__(self, values: Any = ()) -> None:
        pass

    def __copy__(self) -> "FrozenJsonDict":
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> "FrozenJsonDict":
        return self

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("Frozen JSON cannot be modified.")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


class FrozenJsonList(list[Any]):
    """A JSON-serializable list that rejects in-place mutation."""

    def __new__(cls, values: Any = ()) -> "FrozenJsonList":
        instance = super().__new__(cls)
        list.extend(instance, values)
        return instance

    def __init__(self, values: Any = ()) -> None:
        pass

    def __copy__(self) -> "FrozenJsonList":
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> "FrozenJsonList":
        return self

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("Frozen JSON cannot be modified.")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


def freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Tool JSON object keys must be strings.")
        return FrozenJsonDict(
            (key, freeze_json(child)) for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return FrozenJsonList(freeze_json(child) for child in value)
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is float and isfinite(value):
        return value
    raise ValueError("Tool JSON contains a non-JSON value.")


@dataclass(frozen=True)
class ToolRef:
    tool_id: str
    version_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.tool_id, str)
            or not self.tool_id.strip()
            or not isinstance(self.version_id, str)
            or not self.version_id.strip()
        ):
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
        object.__setattr__(self, "input_schema", freeze_json(self.input_schema))
        object.__setattr__(self, "output_schema", freeze_json(self.output_schema))
        object.__setattr__(self, "execution_spec", freeze_json(self.execution_spec))
        object.__setattr__(
            self,
            "allowed_access_sources",
            tuple(self.allowed_access_sources),
        )


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

    restricted = json.loads(json.dumps(schema, ensure_ascii=False, allow_nan=False))
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
                "$defs",
                "definitions",
                "pattern",
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
            raise ValueError("Tool schema uses an unsupported keyword.")

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
class ToolSource:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    mcp_server_id: str | None = None
    kind: str = "builtin"
    name: str = ""
    status: str = "active"
    created_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class Tool:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    source_id: str = ""
    kind: str = "builtin"
    stable_key: str = ""
    function_name: str = ""
    current_version_id: str | None = None
    status: str = "active"
    availability: str = "available"
    created_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class ToolDraft:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    tool_id: str = ""
    display_name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    execution_spec: dict[str, Any] = field(default_factory=dict)
    revision: int = 1
    updated_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class ToolVersion:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    tool_id: str = ""
    revision: int = 1
    display_name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    execution_spec: dict[str, Any] = field(default_factory=dict)
    definition_hash: str = ""
    created_by_user_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class ToolPolicy:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    tool_id: str = ""
    tool_version_id: str = ""
    definition_hash: str = ""
    revision: int = 1
    approval: str = "each_call"
    effect: str = "unknown"
    allowed_access_sources: list[str] = field(default_factory=list)
    workflow_callable: bool = False
    parallel_safe: bool = False
    reviewed_by_user_id: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class ApplicationToolBinding:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    application_id: str = ""
    tool_id: str = ""
    tool_version_id: str = ""
    bound_by_user_id: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class ToolInvocation:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    origin: str = "test"
    root_run_id: str | None = None
    run_id: str | None = None
    invocation_id: str = ""
    execution_user_id: str = ""
    access_source: str = "console"
    tool_id: str = ""
    tool_version_id: str = ""
    policy_snapshot: dict[str, Any] = field(default_factory=dict)
    arguments: dict[str, Any] = field(default_factory=dict)
    arguments_hash: str = ""
    idempotency_key: str = ""
    status: str = "queued"
    attempts: int = 0
    max_attempts: int = 3
    approved_by_user_id: str | None = None
    approved_at: datetime | None = None
    worker_task_id: str | None = None
    lease_expires_at: datetime | None = None
    result_data: Any = None
    result_summary: str = ""
    outcome: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class McpServer:
    id: str = field(default_factory=new_id)
    workspace_id: str = ""
    name: str = ""
    transport: str = "streamable_http"
    network_policy: str = "deployment"
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
