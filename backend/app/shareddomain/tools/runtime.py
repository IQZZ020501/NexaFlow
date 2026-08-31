"""Pure contracts shared by Tool lifecycle and execution use cases."""

from dataclasses import asdict
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator

from app.entities.tools import Tool, ToolPolicy, ToolSnapshot, ToolSource, ToolVersion


# Leave room for the JSON envelope around the sandbox's 256 KiB code limit.
MAX_TOOL_INPUT_BYTES = 512 * 1024
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
    return json.loads(
        json.dumps(asdict(snapshot), ensure_ascii=False, allow_nan=False)
    )


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


def tool_arguments_hash(arguments: dict[str, Any]) -> str:
    return hashlib.sha256(_encoded_json(arguments, MAX_TOOL_INPUT_BYTES)).hexdigest()


def normalize_tool_arguments(
    function_name: str,
    input_schema: dict[str, Any],
    arguments: Any,
) -> Any:
    """Accept the two legacy envelopes still emitted by some chat models."""
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

    if function_name != "pptx_skill" or not (
        isinstance(properties, dict) and "presentation" in properties
    ):
        return normalized

    presentation = normalized.get("presentation")
    if isinstance(presentation, str):
        try:
            parsed = json.loads(presentation)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            presentation = parsed
    if isinstance(presentation, dict):
        presentation = dict(presentation)
    elif "presentation" not in normalized:
        presentation = {}
    else:
        presentation = None

    if "filename" not in normalized and "file_name" in normalized:
        normalized["filename"] = normalized["file_name"]
    normalized.pop("file_name", None)

    aliases = {
        "file_title": "title",
        "file_subtitle": "subtitle",
    }
    if presentation is not None:
        for source, target in aliases.items():
            if source in presentation:
                if target not in presentation:
                    presentation[target] = presentation[source]
                presentation.pop(source, None)
    for source, target in aliases.items():
        if source in normalized:
            if presentation is not None and target not in presentation:
                presentation[target] = normalized[source]
            normalized.pop(source, None)

    for field in (
        "title",
        "subtitle",
        "slides",
        "template",
        "brand",
        "theme",
        "footer",
    ):
        if field in normalized:
            if presentation is not None and field not in presentation:
                presentation[field] = normalized[field]
            normalized.pop(field, None)

    if presentation is not None:
        normalized["presentation"] = presentation
    return normalized


def validate_tool_arguments(
    snapshot: ToolSnapshot,
    arguments: dict[str, Any],
) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")
    _encoded_json(arguments, MAX_TOOL_INPUT_BYTES)
    _validate_schema(snapshot.input_schema, arguments, "Tool arguments are invalid.")


def validate_tool_output(snapshot: ToolSnapshot, data: Any) -> None:
    _encoded_json(data, MAX_TOOL_RESULT_BYTES)
    if snapshot.output_schema is not None:
        _validate_schema(snapshot.output_schema, data, "Tool output is invalid.")


def exhausted_tool_invocation_terminal_state(
    invocation_status: str,
    effect: str | None,
) -> tuple[str, str, str, str]:
    uncertain = (
        invocation_status == TOOL_INVOCATION_RUNNING
        and effect not in TOOL_SAFE_EXTERNAL_EFFECTS
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
        path = ".".join(str(part) for part in error.absolute_path) or "root"
        detail = f"{message} at {path}: {error.message}."
        properties = schema.get("properties")
        if path == "root" and isinstance(properties, dict):
            detail += f" Expected fields: {', '.join(str(key) for key in properties)}."
        raise ValueError(detail[:1000])


__all__ = [
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
    "exhausted_tool_invocation_terminal_state",
    "normalize_tool_arguments",
    "tool_arguments_hash",
    "tool_snapshot_from_payload",
    "tool_snapshot_payload",
    "validate_tool_arguments",
    "validate_tool_output",
]
