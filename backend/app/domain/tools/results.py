"""Bound model-visible Tool output while retaining an exact durable JSON value."""

import json
from typing import Any

from app.domain.tools.runtime import MAX_TOOL_RESULT_BYTES
from app.ports.mcp import MAX_MCP_RESULT_BYTES, MAX_MCP_STORED_RESULT_BYTES


def prepare_shell_result(
    payload: dict[str, Any], result_id: str
) -> tuple[dict[str, Any], str | None]:
    """Budget the encoded envelope, keeping exit status and artifact references."""
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) <= MAX_TOOL_RESULT_BYTES:
        return payload, None
    retained = len(encoded.encode("utf-8")) <= MAX_MCP_STORED_RESULT_BYTES
    preview = {
        **payload,
        "truncated": True,
        "full_result_available": retained,
        "summary": (
            "Command result preview. Use read_tool_result(result_id, offset, limit) "
            "to read the saved JSON logs; follow next_offset until null."
            if retained
            else "Command result preview only; full logs exceed the storage limit."
        ),
    }
    if retained:
        preview.update(result_id=result_id, total_characters=len(encoded))
    while (
        len(json.dumps(preview, ensure_ascii=False).encode("utf-8"))
        > MAX_TOOL_RESULT_BYTES
    ):
        logs = [name for name in ("stdout", "stderr") if preview.get(name)]
        if not logs:
            # Never drop exit status or artifact references to make room for logs.
            raise ValueError("Command result metadata exceeds its size limit.")
        name = max(
            logs,
            key=lambda key: len(json.dumps(preview[key], ensure_ascii=False).encode()),
        )
        preview[name] = preview[name][: len(preview[name]) // 2]
    return preview, encoded if retained else None


def prepare_mcp_result(
    payload: dict[str, Any], result_id: str | None
) -> tuple[dict[str, Any], str | None]:
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    size = len(encoded.encode("utf-8"))
    if size <= MAX_MCP_RESULT_BYTES:
        return payload, None
    retained = bool(result_id) and size <= MAX_MCP_STORED_RESULT_BYTES
    preview: dict[str, Any] = {
        "content": [{"type": "text", "text": ""}],
        "isError": bool(payload.get("isError")),
        "_meta": {
            "nexaflow/truncated": True,
            "nexaflow/full_result_available": retained,
            "nexaflow/result_bytes": size,
        },
    }
    if retained:
        preview.update(
            result_id=result_id,
            total_characters=len(encoded),
            summary=(
                "MCP result preview. The complete JSON, including content blocks, "
                "structuredContent and metadata, is saved in the Tool ledger. "
                "Use read_tool_result(result_id, offset, limit) to read it in "
                "character ranges; follow next_offset until it is null."
            ),
        )
    else:
        preview["summary"] = (
            "MCP result preview only. The complete result could not be retained "
            "within the storage limit or outside a durable invocation."
        )
    prefix_chars = min(len(encoded), 8000)
    while True:
        preview["content"][0]["text"] = encoded[:prefix_chars]
        if (
            len(json.dumps(preview, ensure_ascii=False).encode())
            <= MAX_MCP_RESULT_BYTES
        ):
            return preview, encoded if retained else None
        prefix_chars //= 2


def tool_result_page(
    result_id: str, content: str, offset: int, total_characters: int
) -> dict[str, Any]:
    """Keep escaped JSON and multibyte text within the same context payload cap."""
    while True:
        end = offset + len(content)
        page = {
            "result_id": result_id,
            "offset": offset,
            "next_offset": end if end < total_characters else None,
            "total_characters": total_characters,
            "content": content,
        }
        if len(json.dumps(page, ensure_ascii=False).encode()) <= MAX_MCP_RESULT_BYTES:
            return page
        content = content[: len(content) // 2]
