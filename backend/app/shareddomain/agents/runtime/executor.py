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
from app.shareddomain.agents.runtime.usage import empty_usage, merge_usage

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentExecutionResult:
    content: str
    events: list[dict[str, Any]]
    model_usage: dict[str, Any]
    grounding_status: str = "skipped"
    grounding_meta: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentGroundingResult:
    status: str
    answer: str
    meta: dict[str, Any]
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
GroundingHandler = Callable[
    [str, list[dict[str, Any]]],
    Awaitable[AgentGroundingResult],
]
TERMINAL_GROUNDING_STATUSES = frozenset(
    {"verified", "revised", "insufficient", "unavailable", "skipped"}
)


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
    max_model_tokens: int | None = None,
    grounding_handler: GroundingHandler | None = None,
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
    grounding_pending = (
        grounding_handler is not None
        and initial_state["grounding_status"] not in TERMINAL_GROUNDING_STATUSES
    )
    has_draft = bool(initial_state["draft_answer"] or initial_state["final_answer"])
    if initial_state["final_answer"] and not grounding_pending:
        return AgentExecutionResult(
            content=initial_state["final_answer"],
            events=initial_state["events"],
            model_usage=initial_state["model_usage"],
            grounding_status=initial_state["grounding_status"],
            grounding_meta=initial_state["grounding_meta"],
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
    if not (grounding_pending and has_draft):
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
                max_model_tokens=max_model_tokens,
                defer_answer=grounding_handler is not None,
            ),
            stream_mode="values",
        ):
            state = value
            if on_checkpoint is not None:
                if (
                    state["final_answer"]
                    and grounding_handler is None
                    and state["grounding_status"] == "not_started"
                ):
                    state = {
                        **state,
                        "grounding_status": "skipped",
                        "grounding_meta": {"reason": "no_grounding_source"},
                    }
                phase = (
                    "done"
                    if state["final_answer"] and grounding_handler is None
                    else "agent"
                )
                if state["pending_tool_calls"]:
                    phase = "tool"
                await on_checkpoint(serialize_agent_state(state), phase)

    if grounding_handler is not None and state["grounding_status"] not in TERMINAL_GROUNDING_STATUSES:
        draft_answer = state["draft_answer"] or state["final_answer"]
        if not draft_answer.strip():
            raise RuntimeError("Agent grounding received an empty draft.")
        state = {
            **state,
            "draft_answer": draft_answer,
            "final_answer": "",
            "grounding_status": "pending",
        }
        if on_checkpoint is not None:
            await on_checkpoint(serialize_agent_state(state), "grounding")
        running_event = {
            "type": "thought",
            "turn": state["turn"],
            "tool_name": "",
            "status": "running",
            "summary": "agent.grounding_check",
            "call_id": "",
            "tool_label": "",
            "tool_kind": "unknown",
            "server_name": "",
            "input": {},
            "output": None,
            "reasoning": "",
        }
        await callback.process(running_event)
        try:
            grounding = await grounding_handler(
                draft_answer,
                state["evidence_packets"],
            )
        except Exception as exc:
            grounding = AgentGroundingResult(
                status="unavailable",
                answer=draft_answer,
                meta={"error": type(exc).__name__},
                model_usage=empty_usage(),
            )
        summary_by_status = {
            "verified": "agent.grounding_verified",
            "revised": "agent.grounding_revised",
            "insufficient": "agent.grounding_insufficient",
            "unavailable": "agent.grounding_unavailable",
        }
        completed_event = {
            **running_event,
            "status": "succeeded" if grounding.status in {"verified", "revised"} else "failed",
            "summary": summary_by_status.get(
                grounding.status,
                "agent.grounding_unavailable",
            ),
            "output": grounding.meta,
        }
        await callback.process(completed_event)
        state = {
            **state,
            "final_answer": grounding.answer or draft_answer,
            "grounding_status": grounding.status,
            "grounding_meta": grounding.meta,
            "model_usage": merge_usage(state["model_usage"], grounding.model_usage),
        }
        if on_checkpoint is not None:
            await on_checkpoint(serialize_agent_state(state), "done")
        if callback.enabled:
            await callback.process(
                {
                    **running_event,
                    "status": "succeeded",
                    "summary": "agent.answer_ready",
                    "reasoning": "",
                }
            )
            await callback.answer_delta(state["final_answer"])
    elif state["grounding_status"] == "not_started":
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
