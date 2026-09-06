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
    seen_evidence_ids: list[str]
    no_new_evidence_rounds: int
    pending_tool_calls: list[PendingToolCall]
    finish_reason: str
    draft_answer: str
    final_answer: str
    grounding_status: str
    grounding_meta: dict[str, Any]
    evidence_packets: list[dict[str, Any]]
    model_usage: dict[str, Any]
