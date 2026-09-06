"""Provider-neutral usage normalization for agent and compaction calls."""

from collections.abc import Mapping
from typing import Any


_NUMERIC_KEYS = (
    "model_calls",
    "reported_model_calls",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def empty_usage() -> dict[str, Any]:
    return {
        **{key: 0 for key in _NUMERIC_KEYS},
        "input_token_details": {},
        "output_token_details": {},
        "compaction": {key: 0 for key in _NUMERIC_KEYS},
    }


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_number(sources: list[Mapping[str, Any]], keys: tuple[str, ...]) -> tuple[int, bool]:
    for source in sources:
        for key in keys:
            value = _number(source.get(key))
            if value is not None:
                return value, True
    return 0, False


def _details(sources: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    for source in sources:
        values: dict[str, int] = {}
        nested = _mapping(source.get(key))
        for name, value in nested.items():
            number = _number(value)
            if number is not None:
                values[name] = number
        if values:
            return values
    return {}


def usage_from_message(message: Any) -> dict[str, Any]:
    """Return one normalized usage record, even when a provider reports nothing."""
    metadata = _mapping(getattr(message, "usage_metadata", None))
    response = _mapping(getattr(message, "response_metadata", None))
    response_usage = _mapping(response.get("usage"))
    response_token_usage = _mapping(response.get("token_usage"))
    sources = [metadata, response_usage, response_token_usage, response]

    input_tokens, has_input = _first_number(
        sources, ("input_tokens", "prompt_tokens")
    )
    output_tokens, has_output = _first_number(
        sources, ("output_tokens", "completion_tokens")
    )
    total_tokens, has_total = _first_number(sources, ("total_tokens",))
    if not has_total and (has_input or has_output):
        total_tokens = input_tokens + output_tokens

    input_details = _details(
        [metadata, response_usage, response_token_usage], "input_token_details"
    )
    output_details = _details(
        [metadata, response_usage, response_token_usage], "output_token_details"
    )
    cache_read, has_cache_read = _first_number(
        [metadata, input_details, response_usage, response_token_usage, response],
        ("cache_read_input_tokens", "cache_read"),
    )
    cache_creation, has_cache_creation = _first_number(
        [metadata, input_details, response_usage, response_token_usage, response],
        ("cache_creation_input_tokens", "cache_creation"),
    )
    if has_cache_read:
        input_details["cache_read"] = cache_read
    if has_cache_creation:
        input_details["cache_creation"] = cache_creation

    reported = has_input or has_output or has_total or has_cache_read or has_cache_creation
    return {
        "model_calls": 1,
        "reported_model_calls": 1 if reported else 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "input_token_details": input_details,
        "output_token_details": output_details,
    }


def _merge_mapping(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, Mapping):
            merged[key] = _merge_mapping(_mapping(merged.get(key)), value)
            continue
        number = _number(value)
        if number is not None:
            previous = _number(merged.get(key)) or 0
            merged[key] = previous + number
        elif key not in merged:
            merged[key] = value
    return merged


def merge_usage(*records: Mapping[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = empty_usage()
    for record in records:
        if record:
            merged = _merge_mapping(merged, record)
    return merged


def add_compaction_usage(
    total: Mapping[str, Any] | None,
    compaction: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return merge_usage(total, compaction, {"compaction": compaction or {}})


__all__ = [
    "add_compaction_usage",
    "empty_usage",
    "merge_usage",
    "usage_from_message",
]
