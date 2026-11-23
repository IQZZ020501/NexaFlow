"""Session harness: capabilities, context, queued input, and lifecycle hooks."""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage

from app.domain.agents.runtime.callbacks import CompactionProgressHandler
from app.domain.agents.runtime.capabilities import CATALOG_MARKER, CapabilityRegistry
from app.domain.agents.runtime.context import AgentContextManager
from app.domain.agents.runtime.references import (
    REFERENCE_MARKER,
    collect_references,
    reference_message,
)
from app.domain.agents.runtime.state import AgentState
from app.domain.agents.runtime.usage import merge_usage

SessionInputSource = Callable[[list[int]], Awaitable[list[dict[str, Any]]]]
PERSONAL_CONTEXT_MARKER = "nexaflow_personal_context"


class AgentSession:
    def __init__(
        self,
        capabilities: CapabilityRegistry,
        context: AgentContextManager | None = None,
        input_source: SessionInputSource | None = None,
        reference_source: Callable[[], Awaitable[dict]] | None = None,
        personal_context: Callable[[AgentState], Awaitable[str]] | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.context = context
        self.input_source = input_source
        self.reference_source = reference_source
        self.personal_context = personal_context

    async def apply_follow_ups(self, state: AgentState) -> tuple[AgentState, bool]:
        harness = dict(state.get("harness") or {})
        consumed = list(harness.get("input_ids", []))
        inputs = await self.input_source(consumed) if self.input_source else []
        inputs = [item for item in inputs if item["id"] not in consumed]
        if not inputs:
            return state, False
        if state.get("final_answer"):
            inputs = [
                {
                    **inputs[0],
                    "previous_answer": state["final_answer"],
                    "previous_answer_turn": state["turn"],
                },
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

    async def prepare_turn(
        self, state: AgentState, *, on_compaction: CompactionProgressHandler | None = None
    ) -> AgentState:
        self.capabilities.restore(state.get("harness") or {})
        messages = await self.capabilities.extensions.prepare_context(
            [
                message
                for message in state["messages"]
                if not any(
                    message.additional_kwargs.get(key)
                    for key in (REFERENCE_MARKER, CATALOG_MARKER, PERSONAL_CONTEXT_MARKER)
                )
            ]
        )
        usage = state["model_usage"]
        harness = {**state.get("harness", {}), **self.capabilities.snapshot()}
        if "exact_references" not in harness and self.reference_source is not None:
            harness["exact_references"] = await self.reference_source()
        references = collect_references(harness, state["events"])
        harness["exact_references"] = references
        projection = reference_message(references)
        if projection is not None:
            messages.append(projection)
        catalog = self.capabilities.catalog_message()
        if catalog is not None:
            messages.append(catalog)
        if self.context is not None:
            self.context.restore(harness.get("context_memory"))
            messages, compaction_usage = await self.context.prepare(
                messages, self.capabilities.tools, on_compaction=on_compaction
            )
            # Compaction may replace the projection with prose. Always restore
            # the authoritative projection from the checkpoint, exactly once.
            messages = [
                m for m in messages
                if not any(
                    m.additional_kwargs.get(key)
                    for key in (REFERENCE_MARKER, CATALOG_MARKER)
                )
            ]
            if projection is not None:
                messages.append(projection)
            if catalog is not None:
                messages.append(catalog)
            usage = merge_usage(usage, compaction_usage)
            if self.context.memory is not None:
                harness["context_memory"] = self.context.snapshot()
            if compaction_usage["model_calls"]:
                harness["compaction_count"] = (
                    int(harness.get("compaction_count", 0)) + 1
                )
        # Refresh after compaction so removed memories never survive in a summary
        # or a resumed checkpoint's personalization projection.
        if self.personal_context is not None:
            personal = await self.personal_context(state)
            if personal:
                personal_message = HumanMessage(
                    content=personal,
                    additional_kwargs={PERSONAL_CONTEXT_MARKER: True},
                )
                if self.context is None or self.context.tokens(
                    [*messages, personal_message], self.capabilities.tools
                ) <= int(self.context.context_window * 0.8) - min(
                    4096, self.context.context_window // 4
                ):
                    messages.append(personal_message)
        return {**state, "messages": messages, "model_usage": usage, "harness": harness}
