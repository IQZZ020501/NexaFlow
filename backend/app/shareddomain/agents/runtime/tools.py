import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import validators
from jsonschema.exceptions import SchemaError
from langchain_core.tools import StructuredTool


@dataclass(frozen=True)
class AgentToolResult:
    content: str
    summary: str
    output: Any = None
    is_error: bool = False
    outcome_uncertain: bool = False
    evidence_ids: frozenset[str] = frozenset()


class AgentExecutionPaused(Exception):
    """The durable executor must persist state before continuing this call."""

    def __init__(self, call_id: str, reason: str) -> None:
        super().__init__(reason)
        self.call_id = call_id
        self.reason = reason


class AgentToolUncertain(AgentExecutionPaused):
    """A side effect may have happened but its result was not durably recorded."""

    def __init__(self, call_id: str, reason: str) -> None:
        super().__init__(call_id, reason)


class AgentToolBusy(AgentExecutionPaused):
    """Another worker currently owns the tool-call lease."""

    def __init__(self, call_id: str, reason: str) -> None:
        super().__init__(call_id, reason)


def create_agent_tool(
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
    execute: Callable[[str], Awaitable[AgentToolResult]],
    display_name: str = "",
    kind: str = "unknown",
    server_name: str = "",
    parallel_safe: bool = False,
    policy_mode: str = "",
    server_id: str = "",
    definition_hash: str = "",
    source_tool_name: str = "",
) -> StructuredTool:
    try:
        validator_type = validators.validator_for(parameters)
        validator_type.check_schema(parameters)
    except SchemaError as exc:
        raise ValueError("Tool schema is invalid.") from exc
    if parameters.get("type") != "object":
        raise ValueError("Tool schema must describe an object.")
    validator = validator_type(parameters)

    async def invoke(**arguments: Any) -> AgentToolResult:
        if next(validator.iter_errors(arguments), None) is not None:
            return AgentToolResult(
                content="Tool parameters are invalid.",
                summary="Invalid tool parameters.",
                is_error=True,
            )
        return await execute(json.dumps(arguments, ensure_ascii=False))

    return StructuredTool.from_function(
        coroutine=invoke,
        name=name,
        description=description,
        args_schema=parameters,
        infer_schema=False,
        metadata={
            "display_name": display_name,
            "kind": kind,
            "server_name": server_name,
            "parallel_safe": parallel_safe,
            "policy_mode": policy_mode,
            "server_id": server_id,
            "definition_hash": definition_hash,
            "source_tool_name": source_tool_name,
        },
    )


def agent_tool_metadata(tool: StructuredTool) -> dict[str, str]:
    metadata = tool.metadata or {}
    return {
        "display_name": str(metadata.get("display_name") or tool.name),
        "kind": str(metadata.get("kind") or "unknown"),
        "server_name": str(metadata.get("server_name") or ""),
        "policy_mode": str(metadata.get("policy_mode") or ""),
        "server_id": str(metadata.get("server_id") or ""),
        "definition_hash": str(metadata.get("definition_hash") or ""),
        "source_tool_name": str(metadata.get("source_tool_name") or ""),
    }


def is_parallel_safe(tool: StructuredTool) -> bool:
    return bool((tool.metadata or {}).get("parallel_safe", False))
