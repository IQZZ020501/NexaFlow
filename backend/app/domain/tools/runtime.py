"""Pure contracts shared by Tool lifecycle and execution use cases."""

import hashlib
import json
from dataclasses import asdict
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from app.entities.tools import Tool, ToolPolicy, ToolSnapshot, ToolSource, ToolVersion

# Leave room for the JSON envelope around the sandbox's 256 KiB code limit.
MAX_TOOL_INPUT_BYTES = 512 * 1024
# Documents Skill reference DOCX input is bounded separately from ordinary tools.
MAX_DOCUMENT_TOOL_INPUT_BYTES = 8 * 1024 * 1024
MAX_TOOL_RESULT_BYTES = 32 * 1024
TOOL_APPROVAL_AUTO = "auto"
TOOL_APPROVAL_DISABLED = "disabled"
TOOL_APPROVAL_EACH_CALL = "each_call"
TOOL_SAFE_EXTERNAL_EFFECTS = frozenset({"pure", "external_read"})
TOOL_UNCERTAIN_EFFECTS = frozenset({"external_write", "unknown"})
TOOL_INVOCATION_QUEUED = "queued"
TOOL_INVOCATION_AWAITING_APPROVAL = "awaiting_approval"
TOOL_INVOCATION_APPROVED = "approved"
TOOL_INVOCATION_RUNNING = "running"
TOOL_INVOCATION_SUCCEEDED = "succeeded"
TOOL_INVOCATION_FAILED = "failed"
TOOL_INVOCATION_UNCERTAIN = "uncertain"
TOOL_INVOCATION_TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "rejected", "uncertain", "cancelled"}
)
TOOL_INVOCATION_CLAIMABLE_STATUSES = (
    TOOL_INVOCATION_QUEUED,
    TOOL_INVOCATION_APPROVED,
)


def effective_tool_access_sources(
    allowed_access_sources: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Treat public chat as an interactive extension of console access.

    Older immutable Tool snapshots and existing workspace policies may only
    record ``console``. Public chat has its own authenticated approval flow, so
    console access also grants public access without widening machine-to-machine
    API access.
    """
    sources = list(dict.fromkeys(allowed_access_sources))
    if "console" in sources and "public" not in sources:
        sources.append("public")
    return tuple(sources)


def tool_access_source_allowed(
    allowed_access_sources: tuple[str, ...] | list[str],
    access_source: str,
) -> bool:
    return access_source in effective_tool_access_sources(allowed_access_sources)


def build_tool_snapshot(
    tool: Tool,
    source: ToolSource,
    version: ToolVersion,
    policy: ToolPolicy,
    bound_by_user_id: str,
) -> ToolSnapshot:
    if (
        tool.workspace_id != source.workspace_id
        or tool.workspace_id != version.workspace_id
    ):
        raise ValueError("Tool snapshot resources must share a workspace.")
    if tool.source_id != source.id or version.tool_id != tool.id:
        raise ValueError("Tool snapshot resources do not match.")
    if policy.tool_id != tool.id or policy.tool_version_id != version.id:
        raise ValueError("Tool snapshot policy does not match its version.")
    return ToolSnapshot(
        schema_version=1,
        tool_id=tool.id,
        version_id=version.id,
        source_id=source.id,
        kind=tool.kind,
        function_name=tool.function_name,
        display_name=version.display_name,
        description=version.description,
        input_schema=version.input_schema,
        output_schema=version.output_schema,
        definition_hash=version.definition_hash,
        policy_id=policy.id,
        policy_revision=policy.revision,
        bound_by_user_id=bound_by_user_id,
        approval=policy.approval,
        effect=policy.effect,
        allowed_access_sources=tuple(policy.allowed_access_sources),
        workflow_callable=policy.workflow_callable,
        parallel_safe=policy.parallel_safe,
        execution_spec=version.execution_spec,
    )


def tool_snapshot_payload(snapshot: ToolSnapshot) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(snapshot), ensure_ascii=False, allow_nan=False))


def tool_snapshot_from_payload(payload: Any) -> ToolSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("Tool invocation snapshot is invalid.")
    values = dict(payload)
    allowed_sources = values.get("allowed_access_sources")
    if not isinstance(allowed_sources, list):
        raise ValueError("Tool invocation snapshot is invalid.")
    values["allowed_access_sources"] = tuple(allowed_sources)
    try:
        return ToolSnapshot(**values)
    except (TypeError, ValueError) as exc:
        raise ValueError("Tool invocation snapshot is invalid.") from exc


def tool_arguments_hash(
    arguments: dict[str, Any], *, max_bytes: int = MAX_TOOL_INPUT_BYTES
) -> str:
    return hashlib.sha256(_encoded_json(arguments, max_bytes)).hexdigest()


def tool_input_size_limit(snapshot: ToolSnapshot) -> int:
    properties = snapshot.input_schema.get("properties")
    if (
        snapshot.function_name == "documents_skill"
        and isinstance(properties, dict)
        and "reference_docx_base64" in properties
    ):
        return MAX_DOCUMENT_TOOL_INPUT_BYTES
    return MAX_TOOL_INPUT_BYTES


def normalize_tool_arguments(
    function_name: str,
    input_schema: dict[str, Any],
    arguments: Any,
) -> Any:
    """Accept a serialized arguments envelope emitted by some chat models."""
    if not isinstance(arguments, dict):
        return arguments
    properties = input_schema.get("properties")
    has_arguments_field = isinstance(properties, dict) and "arguments" in properties
    normalized = dict(arguments)
    if not has_arguments_field and set(normalized) == {"arguments"}:
        wrapped = normalized["arguments"]
        if isinstance(wrapped, str):
            try:
                wrapped = json.loads(wrapped)
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(wrapped, dict):
            normalized = dict(wrapped)

    return normalized


def validate_tool_arguments(
    snapshot: ToolSnapshot,
    arguments: dict[str, Any],
) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")
    _encoded_json(arguments, tool_input_size_limit(snapshot))
    _validate_schema(snapshot.input_schema, arguments, "Tool arguments are invalid.")


def validate_tool_output(snapshot: ToolSnapshot, data: Any) -> None:
    _encoded_json(data, MAX_TOOL_RESULT_BYTES)
    if snapshot.output_schema is not None:
        _validate_schema(snapshot.output_schema, data, "Tool output is invalid.")


def exhausted_tool_invocation_terminal_state(
    invocation_status: str,
    effect: str | None,
    *,
    dispatched: bool | None = None,
) -> tuple[str, str, str, str]:
    uncertain = (
        invocation_status == TOOL_INVOCATION_RUNNING
        and effect not in TOOL_SAFE_EXTERNAL_EFFECTS
        and dispatched is not False
    )
    if uncertain:
        return (
            TOOL_INVOCATION_UNCERTAIN,
            "uncertain",
            "Tool outcome is uncertain.",
            "Tool execution was interrupted after dispatch; confirm the external state.",
        )
    return (
        TOOL_INVOCATION_FAILED,
        "confirmed",
        "Tool execution interrupted.",
        "Agent run retry limit reached before the tool completed.",
    )


def _encoded_json(value: Any, limit: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Tool data must be valid JSON.") from exc
    if len(encoded) > limit:
        raise ValueError("Tool data exceeds its size limit.")
    return encoded


def _validate_schema(schema: dict[str, Any], value: Any, message: str) -> None:
    try:
        validator = Draft202012Validator(schema)
        error = next(validator.iter_errors(value), None)
    except Exception as exc:
        raise ValueError("Tool schema could not be resolved.") from exc
    if error is not None:
        path, error_message = schema_validation_error_detail(error)
        detail = f"{message} at {path}: {error_message}."
        properties = schema.get("properties")
        if path == "root" and isinstance(properties, dict):
            detail += f" Expected fields: {', '.join(str(key) for key in properties)}."
        raise ValueError(detail[:1000])


def schema_validation_error_detail(error: ValidationError) -> tuple[str, str]:
    """Return a bounded, actionable message for nested union-schema failures."""
    path = ".".join(str(part) for part in error.absolute_path) or "root"
    if not error.context:
        return path, error.message

    leaves: list[ValidationError] = []
    pending = list(error.context)
    while pending:
        current = pending.pop(0)
        if current.context:
            pending[0:0] = list(current.context)
        else:
            leaves.append(current)

    details: list[str] = []
    for leaf in sorted(leaves, key=lambda item: len(item.absolute_path), reverse=True):
        leaf_path = ".".join(str(part) for part in leaf.absolute_path) or "root"
        rendered = f"at {leaf_path}: {leaf.message}"
        if rendered not in details:
            details.append(rendered)
        if len(details) == 6:
            break
    if not details:
        return path, error.message
    return path, "value does not match a supported shape; " + "; ".join(details)


__all__ = [
    "MAX_DOCUMENT_TOOL_INPUT_BYTES",
    "MAX_TOOL_INPUT_BYTES",
    "MAX_TOOL_RESULT_BYTES",
    "TOOL_APPROVAL_AUTO",
    "TOOL_APPROVAL_DISABLED",
    "TOOL_APPROVAL_EACH_CALL",
    "TOOL_INVOCATION_APPROVED",
    "TOOL_INVOCATION_AWAITING_APPROVAL",
    "TOOL_INVOCATION_CLAIMABLE_STATUSES",
    "TOOL_INVOCATION_FAILED",
    "TOOL_INVOCATION_QUEUED",
    "TOOL_INVOCATION_RUNNING",
    "TOOL_INVOCATION_SUCCEEDED",
    "TOOL_INVOCATION_TERMINAL_STATUSES",
    "TOOL_INVOCATION_UNCERTAIN",
    "TOOL_SAFE_EXTERNAL_EFFECTS",
    "TOOL_UNCERTAIN_EFFECTS",
    "build_tool_snapshot",
    "effective_tool_access_sources",
    "exhausted_tool_invocation_terminal_state",
    "normalize_tool_arguments",
    "schema_validation_error_detail",
    "tool_access_source_allowed",
    "tool_arguments_hash",
    "tool_input_size_limit",
    "tool_snapshot_from_payload",
    "tool_snapshot_payload",
    "validate_tool_arguments",
    "validate_tool_output",
]
