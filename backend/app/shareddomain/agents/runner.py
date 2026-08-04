import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.capabilities.llm.runtime import (
    ModelCompletion,
    ModelProviderError,
    ModelToolCall,
    OpenAICompatibleModelProvider,
)

MAX_AGENT_TURNS = 8
MAX_AGENT_TOOL_CALLS = 12
MAX_RETRIEVAL_CALLS = 4
MAX_EVENT_STRING_CHARS = 2000
MAX_EVENT_LIST_ITEMS = 20
SENSITIVE_FIELD_PARTS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
    "api_key",
)
AgentEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class AgentRunnerError(ModelProviderError):
    pass


@dataclass(frozen=True)
class AgentToolResult:
    content: str
    summary: str
    output: Any = None
    is_error: bool = False


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[[str], Awaitable[AgentToolResult]]
    display_name: str = ""
    kind: str = "unknown"
    server_name: str = ""

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class AgentExecutionResult:
    content: str
    events: list[dict[str, Any]]


def assistant_message(completion: ModelCompletion) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": completion.content or None,
    }
    if completion.tool_calls:
        message["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                },
            }
            for tool_call in completion.tool_calls
        ]
    return message


def tool_message(tool_call: ModelToolCall, result: AgentToolResult) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": result.content,
    }


def safe_event_value(value: Any, field_name: str = "") -> Any:
    normalized_field = field_name.lower()
    if any(part in normalized_field for part in SENSITIVE_FIELD_PARTS):
        return "[REDACTED]"
    if isinstance(value, str):
        return value[:MAX_EVENT_STRING_CHARS]
    if isinstance(value, list):
        return [safe_event_value(item) for item in value[:MAX_EVENT_LIST_ITEMS]]
    if isinstance(value, dict):
        return {
            str(key): safe_event_value(item, str(key))
            for key, item in list(value.items())[:MAX_EVENT_LIST_ITEMS]
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_EVENT_STRING_CHARS]


async def run_agent(
    provider: OpenAICompatibleModelProvider,
    messages: list[dict[str, Any]],
    tools: list[AgentTool],
    on_event: AgentEventHandler | None = None,
) -> AgentExecutionResult:
    tools_by_name = {tool.name: tool for tool in tools}
    definitions = [tool.definition() for tool in tools]
    events: list[dict[str, Any]] = []
    tool_call_count = 0
    retrieval_call_count = 0
    last_evidence_count = -1
    no_new_evidence_turns = 0

    for turn in range(1, MAX_AGENT_TURNS + 1):
        thought_event = {
            "type": "thought",
            "turn": turn,
            "tool_name": "",
            "status": "running",
            "summary": (
                "agent.analyzing"
                if turn == 1
                else "agent.reviewing_tool_results"
            ),
            "call_id": "",
            "tool_label": "",
            "tool_kind": "unknown",
            "server_name": "",
            "input": {},
            "output": None,
        }
        if on_event:
            await on_event({"type": "process", "event": thought_event})

        answer_started = False

        async def emit_answer_delta(delta: str) -> None:
            nonlocal answer_started
            if not on_event:
                return
            if not answer_started:
                answer_started = True
                await on_event(
                    {
                        "type": "process",
                        "event": {
                            **thought_event,
                            "status": "succeeded",
                            "summary": "agent.answer_ready",
                        },
                    }
                )
            await on_event({"type": "answer_delta", "delta": delta})

        if on_event and hasattr(provider, "stream_complete"):
            completion = await provider.stream_complete(
                messages,
                tools=definitions or None,
                on_content_delta=emit_answer_delta,
            )
        else:
            completion = await asyncio.to_thread(
                provider.complete,
                messages,
                tools=definitions or None,
            )
            if on_event and completion.content:
                await emit_answer_delta(completion.content)

        messages.append(assistant_message(completion))

        if not completion.tool_calls:
            if completion.finish_reason == "length":
                raise AgentRunnerError("Agent response was truncated.")
            if not completion.content.strip():
                raise AgentRunnerError("Agent returned an empty response.")
            return AgentExecutionResult(content=completion.content, events=events)

        tool_call_count += len(completion.tool_calls)
        if tool_call_count > MAX_AGENT_TOOL_CALLS:
            raise AgentRunnerError("Agent tool call limit reached.")
        completed_thought = {
            **thought_event,
            "status": "succeeded",
            "summary": "agent.tools_selected",
        }
        if on_event:
            await on_event({"type": "process", "event": completed_thought})

        for tool_call in completion.tool_calls:
            if completion.finish_reason == "length":
                result = AgentToolResult(
                    content="Tool call was not executed because the model response was truncated.",
                    summary="Truncated tool call rejected.",
                    is_error=True,
                )
            else:
                tool = tools_by_name.get(tool_call.name)
                if tool is None:
                    result = AgentToolResult(
                        content=f"Tool {tool_call.name} is not available.",
                        summary="Unknown tool rejected.",
                        is_error=True,
                    )
                else:
                    try:
                        safe_input = safe_event_value(json.loads(tool_call.arguments))
                    except json.JSONDecodeError:
                        safe_input = {}
                    if on_event:
                        await on_event(
                            {
                                "type": "process",
                                "event": {
                                    "type": "tool",
                                    "turn": turn,
                                    "tool_name": tool_call.name,
                                    "status": "running",
                                    "summary": "agent.tool_running",
                                    "call_id": tool_call.id,
                                    "tool_label": tool.display_name or tool.name,
                                    "tool_kind": tool.kind,
                                    "server_name": tool.server_name,
                                    "input": safe_input,
                                    "output": None,
                                },
                            }
                        )
                    try:
                        result = await tool.execute(tool_call.arguments)
                        if tool.kind == "knowledge" and not result.is_error:
                            retrieval_call_count += 1
                            if retrieval_call_count > MAX_RETRIEVAL_CALLS:
                                result = AgentToolResult(
                                    content="Knowledge retrieval limit reached.",
                                    summary="agent.retrieval_limit_reached",
                                    is_error=True,
                                )
                    except Exception:
                        result = AgentToolResult(
                            content="Tool execution failed.",
                            summary="Tool execution failed.",
                            is_error=True,
                        )

            messages.append(tool_message(tool_call, result))
            tool = tools_by_name.get(tool_call.name)
            try:
                safe_input = safe_event_value(json.loads(tool_call.arguments))
            except json.JSONDecodeError:
                safe_input = {}
            event = {
                "type": "tool",
                "turn": turn,
                "tool_name": tool_call.name,
                "status": "failed" if result.is_error else "succeeded",
                "summary": result.summary,
                "call_id": tool_call.id,
                "tool_label": tool.display_name if tool else tool_call.name,
                "tool_kind": tool.kind if tool else "unknown",
                "server_name": tool.server_name if tool else "",
                "input": safe_input,
                "output": safe_event_value(result.output),
            }
            events.append(event)
            if on_event:
                await on_event({"type": "process", "event": event})
            if event["type"] == "tool" and event["status"] == "succeeded":
                output = event.get("output")
                if isinstance(output, dict) and "retrieval_stats" in output:
                    evidence_count = sum(
                        entry.get("submitted", 0)
                        for entry in output["retrieval_stats"]
                    )
                    if evidence_count == last_evidence_count:
                        no_new_evidence_turns += 1
                    else:
                        no_new_evidence_turns = 0
                        last_evidence_count = evidence_count

        if no_new_evidence_turns >= 2:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "No new evidence found in two consecutive retrieval rounds. "
                        "Answer based on what has already been gathered."
                    ),
                }
            )
            no_new_evidence_turns = 0

    raise AgentRunnerError("Agent turn limit reached.")
