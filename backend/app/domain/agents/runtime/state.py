from typing import Any, TypedDict

from langchain_core.messages import BaseMessage


class PendingToolCall(TypedDict):
    id: str
    name: str
    arguments: str


class AgentState(TypedDict):
    messages: list[BaseMessage]
    events: list[dict[str, Any]]
    turn: int
    tool_call_count: int
    pending_tool_calls: list[PendingToolCall]
    finish_reason: str
    final_answer: str
    model_usage: dict[str, Any]
    harness: dict[str, Any]
