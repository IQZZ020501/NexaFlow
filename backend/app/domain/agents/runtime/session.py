"""Session harness: capabilities, context, queued input, and lifecycle hooks."""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage

from app.domain.agents.runtime.capabilities import CapabilityRegistry
from app.domain.agents.runtime.context import AgentContextManager
from app.domain.agents.runtime.state import AgentState
from app.domain.agents.runtime.usage import merge_usage

SessionInputSource = Callable[[list[int], bool], Awaitable[list[dict[str, Any]]]]


class AgentSession:
    def __init__(
        self,
        capabilities: CapabilityRegistry,
        context: AgentContextManager | None = None,
        input_source: SessionInputSource | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.context = context
        self.input_source = input_source

    async def apply_inputs(
        self, state: AgentState, *, settled: bool
    ) -> tuple[AgentState, bool]:
        harness = dict(state.get("harness") or {})
        consumed = list(harness.get("input_ids", []))
        inputs = await self.input_source(consumed, settled) if self.input_source else []
        inputs = [item for item in inputs if item["id"] not in consumed]
        if not inputs:
            return state, False
        if settled and state.get("final_answer"):
            inputs = [
                {**inputs[0], "previous_answer": state["final_answer"]},
                *inputs[1:],
            ]
        harness["input_ids"] = [*consumed, *(item["id"] for item in inputs)]
        harness["inputs"] = [*harness.get("inputs", []), *inputs]
        return {
            **state,
            "messages": [
                *state["messages"],
                *(HumanMessage(content=item["content"]) for item in inputs),
            ],
            "harness": harness,
            "final_answer": "",
        }, True

    async def prepare_turn(self, state: AgentState) -> AgentState:
        self.capabilities.restore(state.get("harness") or {})
        state, _ = await self.apply_inputs(state, settled=False)
        messages = await self.capabilities.extensions.prepare_context(state["messages"])
        usage = state["model_usage"]
        harness = {**state.get("harness", {}), **self.capabilities.snapshot()}
        if self.context is not None:
            messages, compaction_usage = await self.context.prepare(
                messages, self.capabilities.tools
            )
            usage = merge_usage(usage, compaction_usage)
            if compaction_usage["model_calls"]:
                harness["compaction_count"] = (
                    int(harness.get("compaction_count", 0)) + 1
                )
        return {**state, "messages": messages, "model_usage": usage, "harness": harness}
