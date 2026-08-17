import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    convert_to_messages,
    message_to_dict,
    messages_from_dict,
)
from langchain_core.tools import StructuredTool

from app.infrastructure.logger import get_logger, log_event
from app.shareddomain.agents.runtime.callbacks import (
    AgentEventBus,
    AgentEventHandler,
    NexaFlowCallback,
)
from app.shareddomain.agents.runtime.graph import (
    MAX_AGENT_TOOL_CALLS,
    MAX_AGENT_TURNS,
    AgentRuntimeContext,
    agent_graph,
)
from app.shareddomain.agents.runtime.state import AgentState, PendingToolCall
from app.shareddomain.agents.runtime.tools import AgentToolResult
from app.shareddomain.agents.runtime.usage import empty_usage

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentExecutionResult:
    content: str
    events: list[dict[str, Any]]
    model_usage: dict[str, Any]


CheckpointHandler = Callable[[dict[str, Any], str], Awaitable[None]]
BeforeToolCall = Callable[
    [int, PendingToolCall, dict[str, str], dict[str, Any]],
    Awaitable[AgentToolResult | None],
]
AfterToolCall = Callable[
    [int, PendingToolCall, dict[str, str], dict[str, Any], AgentToolResult],
    Awaitable[None],
]


def serialize_agent_state(state: AgentState) -> dict[str, Any]:
    return {
        **state,
        "messages": [message_to_dict(message) for message in state["messages"]],
    }


def deserialize_agent_state(checkpoint: dict[str, Any]) -> AgentState:
    return {
        "messages": messages_from_dict(checkpoint.get("messages", [])),
        "events": list(checkpoint.get("events", [])),
        "turn": int(checkpoint.get("turn", 0)),
        "tool_call_count": int(checkpoint.get("tool_call_count", 0)),
        "seen_evidence_ids": list(checkpoint.get("seen_evidence_ids", [])),
        "no_new_evidence_rounds": int(checkpoint.get("no_new_evidence_rounds", 0)),
        "pending_tool_calls": list(checkpoint.get("pending_tool_calls", [])),
        "finish_reason": str(checkpoint.get("finish_reason", "")),
        "final_answer": str(checkpoint.get("final_answer", "")),
        "model_usage": dict(checkpoint.get("model_usage") or empty_usage()),
    }


async def run_agent(
    model: BaseChatModel,
    messages: list[dict[str, Any]],
    tools: list[StructuredTool],
    on_event: AgentEventHandler | None = None,
    *,
    tool_timeout_seconds: float | None = None,
    checkpoint: dict[str, Any] | None = None,
    on_checkpoint: CheckpointHandler | None = None,
    before_tool_call: BeforeToolCall | None = None,
    after_tool_call: AfterToolCall | None = None,
    initial_usage: dict[str, Any] | None = None,
    max_turns: int = MAX_AGENT_TURNS,
    max_tool_calls: int = MAX_AGENT_TOOL_CALLS,
    max_model_tokens: int | None = None,
) -> AgentExecutionResult:
    initial_state: AgentState = (
        deserialize_agent_state(checkpoint)
        if checkpoint
        else {
            "messages": convert_to_messages(messages),
            "events": [],
            "turn": 0,
            "tool_call_count": 0,
            "seen_evidence_ids": [],
            "no_new_evidence_rounds": 0,
            "pending_tool_calls": [],
            "finish_reason": "",
            "final_answer": "",
            "model_usage": initial_usage or empty_usage(),
        }
    )
    if initial_state["final_answer"]:
        return AgentExecutionResult(
            content=initial_state["final_answer"],
            events=initial_state["events"],
            model_usage=initial_state["model_usage"],
        )
    if checkpoint is None and on_checkpoint is not None:
        await on_checkpoint(serialize_agent_state(initial_state), "agent")
    started_at = time.perf_counter()
    state = initial_state
    async for value in agent_graph.astream(
        initial_state,
        config={"recursion_limit": max_turns * 2 + 1},
        context=AgentRuntimeContext(
            model=model,
            tools=tools,
            callback=NexaFlowCallback(
                AgentEventBus([on_event] if on_event is not None else [])
            ),
            tool_timeout_seconds=tool_timeout_seconds,
            before_tool_call=before_tool_call,
            after_tool_call=after_tool_call,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_model_tokens=max_model_tokens,
        ),
        stream_mode="values",
    ):
        state = value
        if on_checkpoint is not None:
            phase = "done" if state["final_answer"] else (
                "tool" if state["pending_tool_calls"] else "agent"
            )
            await on_checkpoint(serialize_agent_state(state), phase)
    log_event(
        logger,
        logging.INFO,
        "Agent graph execution completed.",
        turns=state["turn"],
        tool_calls=state["tool_call_count"],
        finish_reason=state["finish_reason"],
        duration_ms=round((time.perf_counter() - started_at) * 1000),
    )
    return AgentExecutionResult(
        content=state["final_answer"],
        events=state["events"],
        model_usage=state["model_usage"],
    )
