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

from app.infra.observability.logger import get_logger, log_event
from app.domain.agents.runtime.callbacks import (
    AgentEventBus,
    AgentEventHandler,
    NexaFlowCallback,
)
from app.domain.agents.runtime.graph import (
    MAX_AGENT_KNOWLEDGE_CALLS,
    MAX_AGENT_KNOWLEDGE_ROUNDS,
    MAX_AGENT_TOOL_CALLS,
    MAX_AGENT_TURNS,
    AgentRunnerError,
    AgentRuntimeContext,
    agent_graph,
)
from app.domain.agents.runtime.grounding import (
    GROUNDING_FALLBACK_ANSWER,
    InlineGroundingMode,
)
from app.domain.agents.runtime.state import AgentState, PendingToolCall
from app.domain.agents.runtime.tools import AgentToolResult
from app.domain.agents.runtime.usage import empty_usage

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentExecutionResult:
    content: str
    events: list[dict[str, Any]]
    model_usage: dict[str, Any]
    grounding_status: str = "skipped"
    grounding_meta: dict[str, Any] | None = None


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
    events = list(checkpoint.get("events", []))
    completed_knowledge_events = [
        event
        for event in events
        if event.get("type") == "tool"
        and event.get("tool_kind") == "knowledge"
        and event.get("status") != "running"
    ]
    completed_knowledge_turns = {
        event.get("turn") for event in completed_knowledge_events
    }
    return {
        "messages": messages_from_dict(checkpoint.get("messages", [])),
        "events": events,
        "turn": int(checkpoint.get("turn", 0)),
        "tool_call_count": int(checkpoint.get("tool_call_count", 0)),
        "knowledge_call_count": int(
            checkpoint.get("knowledge_call_count", len(completed_knowledge_events))
        ),
        "knowledge_round_count": int(
            checkpoint.get("knowledge_round_count", len(completed_knowledge_turns))
        ),
        "seen_evidence_ids": list(checkpoint.get("seen_evidence_ids", [])),
        "no_new_evidence_rounds": int(checkpoint.get("no_new_evidence_rounds", 0)),
        "pending_tool_calls": list(checkpoint.get("pending_tool_calls", [])),
        "finish_reason": str(checkpoint.get("finish_reason", "")),
        "draft_answer": str(checkpoint.get("draft_answer", "")),
        "final_answer": str(checkpoint.get("final_answer", "")),
        "grounding_status": str(checkpoint.get("grounding_status", "not_started")),
        "grounding_meta": dict(checkpoint.get("grounding_meta") or {}),
        "evidence_packets": [
            packet
            for packet in checkpoint.get("evidence_packets", [])
            if isinstance(packet, dict)
        ][:32],
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
    max_knowledge_calls: int = MAX_AGENT_KNOWLEDGE_CALLS,
    max_knowledge_rounds: int = MAX_AGENT_KNOWLEDGE_ROUNDS,
    max_model_tokens: int | None = None,
    grounding_mode: InlineGroundingMode | None = None,
    initial_evidence: list[dict[str, Any]] | None = None,
) -> AgentExecutionResult:
    initial_state: AgentState = (
        deserialize_agent_state(checkpoint)
        if checkpoint
        else {
            "messages": convert_to_messages(messages),
            "events": [],
            "turn": 0,
            "tool_call_count": 0,
            "knowledge_call_count": 0,
            "knowledge_round_count": 0,
            "seen_evidence_ids": [],
            "no_new_evidence_rounds": 0,
            "pending_tool_calls": [],
            "finish_reason": "",
            "draft_answer": "",
            "final_answer": "",
            "grounding_status": "not_started",
            "grounding_meta": {},
            "evidence_packets": list(initial_evidence or [])[:32],
            "model_usage": initial_usage or empty_usage(),
        }
    )
    if initial_state["final_answer"]:
        status = initial_state["grounding_status"]
        meta = initial_state["grounding_meta"]
        content = initial_state["final_answer"]
        if status in {"not_started", "pending"}:
            status = "unavailable" if grounding_mode is not None else "skipped"
            meta = {
                "decision": status,
                "error": "legacy_post_generation_checkpoint",
                "mode": "inline" if grounding_mode is not None else "none",
            }
            if grounding_mode == "required":
                content = GROUNDING_FALLBACK_ANSWER
        return AgentExecutionResult(
            content=content,
            events=initial_state["events"],
            model_usage=initial_state["model_usage"],
            grounding_status=status,
            grounding_meta=meta,
        )
    if (
        checkpoint is None
        and on_checkpoint is not None
        and not initial_state["final_answer"]
    ):
        await on_checkpoint(serialize_agent_state(initial_state), "agent")
    started_at = time.perf_counter()
    state = initial_state
    callback = NexaFlowCallback(
        AgentEventBus([on_event] if on_event is not None else [])
    )
    async for value in agent_graph.astream(
        initial_state,
        config={"recursion_limit": max_turns * 2 + 1},
        context=AgentRuntimeContext(
            model=model,
            tools=tools,
            callback=callback,
            tool_timeout_seconds=tool_timeout_seconds,
            before_tool_call=before_tool_call,
            after_tool_call=after_tool_call,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_knowledge_calls=max_knowledge_calls,
            max_knowledge_rounds=max_knowledge_rounds,
            max_model_tokens=max_model_tokens,
            grounding_mode=grounding_mode,
        ),
        stream_mode="values",
    ):
        state = value
        if on_checkpoint is not None:
            if (
                state["final_answer"]
                and state["grounding_status"] == "not_started"
            ):
                state = {
                    **state,
                    "grounding_status": "skipped",
                    "grounding_meta": {"reason": "no_grounding_source"},
                }
            phase = "done" if state["final_answer"] else "agent"
            if state["pending_tool_calls"]:
                phase = "tool"
            await on_checkpoint(serialize_agent_state(state), phase)

    if state["grounding_status"] == "not_started":
        state = {
            **state,
            "grounding_status": "skipped",
            "grounding_meta": {"reason": "no_grounding_source"},
        }
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
        grounding_status=state["grounding_status"],
        grounding_meta=state["grounding_meta"],
    )
