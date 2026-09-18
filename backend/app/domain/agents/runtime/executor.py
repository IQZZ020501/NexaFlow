import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    SystemMessage,
    convert_to_messages,
    message_to_dict,
    messages_from_dict,
)
from langchain_core.tools import StructuredTool

from app.domain.agents.runtime.callbacks import (
    AgentEventBus,
    AgentEventHandler,
    NexaFlowCallback,
)
from app.domain.agents.runtime.graph import (
    MAX_AGENT_TOOL_CALLS,
    MAX_AGENT_TURNS,
    AgentRunnerError,
    AgentRuntimeContext,
    agent_graph,
)
from app.domain.agents.runtime.session import AgentSession
from app.domain.agents.runtime.state import AgentState, PendingToolCall
from app.domain.agents.runtime.tools import AgentToolResult
from app.domain.agents.runtime.usage import empty_usage
from app.infra.observability.logger import get_logger, log_event

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentExecutionResult:
    content: str
    events: list[dict[str, Any]]
    model_usage: dict[str, Any]
    harness: dict[str, Any] = field(default_factory=dict)


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
    """Restore generic execution state, ignoring legacy RAG-only fields."""
    return {
        "messages": messages_from_dict(checkpoint.get("messages", [])),
        "events": [
            event
            for event in checkpoint.get("events", [])
            if not str(event.get("summary") or "").startswith("agent.grounding_")
        ],
        "turn": int(checkpoint.get("turn", 0)),
        "tool_call_count": int(checkpoint.get("tool_call_count", 0)),
        "pending_tool_calls": list(checkpoint.get("pending_tool_calls", [])),
        "finish_reason": str(checkpoint.get("finish_reason", "")),
        "final_answer": str(checkpoint.get("final_answer", "")),
        "model_usage": dict(checkpoint.get("model_usage") or empty_usage()),
        "harness": dict(checkpoint.get("harness") or {}),
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
    session: AgentSession | None = None,
    max_knowledge_calls: int = 6,
    max_knowledge_rounds: int = 3,
    max_no_progress_rounds: int = 2,
    adaptive_retrieval: bool = False,
    knowledge_min_evidence_items: int = 0,
    knowledge_require_source_diversity: bool = False,
    max_model_tokens: int | None = None,
    grounding_mode: str | None = None,
    initial_evidence: list[dict[str, Any]] | None = None,
) -> AgentExecutionResult:
    """Run a model/tool loop independently of any configured capability.

    Legacy retrieval, grounding and cumulative token-budget arguments are
    accepted as no-ops for old callers. Global turn, tool-call and timeout
    circuit breakers remain; model usage is recorded rather than capped here.
    """
    del (
        max_knowledge_calls,
        max_knowledge_rounds,
        max_no_progress_rounds,
        adaptive_retrieval,
        knowledge_min_evidence_items,
        knowledge_require_source_diversity,
        max_model_tokens,
        grounding_mode,
        initial_evidence,
    )
    initial_state: AgentState = (
        deserialize_agent_state(checkpoint)
        if checkpoint
        else {
            "messages": convert_to_messages(messages),
            "events": [],
            "turn": 0,
            "tool_call_count": 0,
            "pending_tool_calls": [],
            "finish_reason": "",
            "final_answer": "",
            "model_usage": initial_usage or empty_usage(),
            "harness": {},
        }
    )
    if checkpoint:
        # A resumed run uses today's execution protocol, not the retired
        # manifest/RAG instructions embedded in a legacy checkpoint.
        system_messages = [
            message
            for message in convert_to_messages(messages)
            if isinstance(message, SystemMessage)
        ]
        if system_messages:
            initial_state["messages"] = [
                *system_messages,
                *[
                    message
                    for message in initial_state["messages"]
                    if not isinstance(message, SystemMessage)
                ],
            ]
    if session is not None:
        session.capabilities.restore(initial_state.get("harness") or {})
        if initial_state["final_answer"]:
            initial_state, continued = await session.apply_inputs(
                initial_state, settled=True
            )
            if continued and initial_state["turn"] >= max_turns:
                raise AgentRunnerError(
                    "Queued session input exceeds the Agent turn budget."
                )
    if initial_state["final_answer"]:
        return AgentExecutionResult(
            content=initial_state["final_answer"],
            events=initial_state["events"],
            model_usage=initial_state["model_usage"],
            harness=initial_state.get("harness", {}),
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
            session=session,
        ),
        stream_mode="values",
    ):
        state = value
        if on_checkpoint is not None:
            phase = "done" if state["final_answer"] else "agent"
            if state["pending_tool_calls"]:
                phase = "tool"
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
        harness=state.get("harness", {}),
    )
