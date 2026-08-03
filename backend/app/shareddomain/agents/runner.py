import asyncio
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


class AgentRunnerError(ModelProviderError):
    pass


@dataclass(frozen=True)
class AgentToolResult:
    content: str
    summary: str
    is_error: bool = False


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[[str], Awaitable[AgentToolResult]]

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


async def run_agent(
    provider: OpenAICompatibleModelProvider,
    messages: list[dict[str, Any]],
    tools: list[AgentTool],
) -> AgentExecutionResult:
    tools_by_name = {tool.name: tool for tool in tools}
    definitions = [tool.definition() for tool in tools]
    events: list[dict[str, Any]] = []
    tool_call_count = 0

    for turn in range(1, MAX_AGENT_TURNS + 1):
        completion = await asyncio.to_thread(
            provider.complete,
            messages,
            tools=definitions or None,
        )
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
                        result = await tool.execute(tool_call.arguments)
                    except Exception:
                        result = AgentToolResult(
                            content="Tool execution failed.",
                            summary="Tool execution failed.",
                            is_error=True,
                        )

            messages.append(tool_message(tool_call, result))
            events.append(
                {
                    "turn": turn,
                    "tool_name": tool_call.name,
                    "status": "failed" if result.is_error else "succeeded",
                    "summary": result.summary,
                }
            )

    raise AgentRunnerError("Agent turn limit reached.")
