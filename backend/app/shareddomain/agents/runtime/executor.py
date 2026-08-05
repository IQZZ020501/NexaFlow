import logging
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import convert_to_messages
from langchain_core.tools import StructuredTool

from app.infrastructure.logger import get_logger, log_event
from app.shareddomain.agents.runtime.callbacks import (
    AgentEventBus,
    AgentEventHandler,
    NexaFlowCallback,
)
from app.shareddomain.agents.runtime.graph import (
    MAX_AGENT_TURNS,
    AgentRuntimeContext,
    agent_graph,
)
from app.shareddomain.agents.runtime.state import AgentState

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentExecutionResult:
    content: str
    events: list[dict[str, Any]]


async def run_agent(
    model: BaseChatModel,
    messages: list[dict[str, Any]],
    tools: list[StructuredTool],
    on_event: AgentEventHandler | None = None,
) -> AgentExecutionResult:
    initial_state: AgentState = {
        "messages": convert_to_messages(messages),
        "events": [],
        "turn": 0,
        "tool_call_count": 0,
        "seen_evidence_ids": [],
        "no_new_evidence_rounds": 0,
        "pending_tool_calls": [],
        "finish_reason": "",
        "final_answer": "",
    }
    started_at = time.perf_counter()
    state = await agent_graph.ainvoke(
        initial_state,
        config={"recursion_limit": MAX_AGENT_TURNS * 2 + 1},
        context=AgentRuntimeContext(
            model=model,
            tools=tools,
            callback=NexaFlowCallback(
                AgentEventBus([on_event] if on_event is not None else [])
            ),
        ),
    )
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
    )
