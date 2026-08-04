import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
    message_chunk_to_message,
)
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.capabilities.llm.runtime import (
    ModelCompletion,
    ModelProviderError,
    ModelToolCall,
)
from app.shareddomain.agents.runtime.callbacks import NexaFlowCallback
from app.shareddomain.agents.runtime.state import AgentState, PendingToolCall
from app.shareddomain.agents.runtime.tools import (
    AgentToolResult,
    agent_tool_metadata,
    is_parallel_safe,
)

MAX_AGENT_TURNS = 8
MAX_AGENT_TOOL_CALLS = 12
MAX_REASONING_CHARS = 6000


class AgentRunnerError(ModelProviderError):
    pass


@dataclass(frozen=True)
class AgentRuntimeContext:
    model: BaseChatModel
    tools: list[StructuredTool]
    callback: NexaFlowCallback


@dataclass(frozen=True)
class PreparedToolCall:
    call: PendingToolCall
    tool: StructuredTool | None
    metadata: dict[str, str]
    arguments: dict[str, Any] | None
    blocked_result: AgentToolResult | None
    parallel_safe: bool


def model_completion(message: AIMessage) -> ModelCompletion:
    tool_calls = [
        ModelToolCall(
            id=tool_call.get("id") or "",
            name=tool_call.get("name") or "",
            arguments=json.dumps(tool_call.get("args") or {}, ensure_ascii=False),
        )
        for tool_call in message.tool_calls
    ]
    tool_calls.extend(
        ModelToolCall(
            id=tool_call.get("id") or "",
            name=tool_call.get("name") or "",
            arguments=tool_call.get("args") or "",
        )
        for tool_call in message.invalid_tool_calls
    )
    finish_reason = message.response_metadata.get("finish_reason") or "stop"
    return ModelCompletion(
        content=message.text,
        tool_calls=tuple(tool_calls),
        finish_reason=str(finish_reason),
    )


def reasoning_content(message: AIMessageChunk) -> str:
    reasoning = message.additional_kwargs.get("reasoning_content")
    return reasoning if isinstance(reasoning, str) else ""


def tool_message(tool_call: PendingToolCall, result: AgentToolResult) -> ToolMessage:
    return ToolMessage(
        content=result.content,
        tool_call_id=tool_call["id"],
    )


def pending_tool_call(tool_call: ModelToolCall) -> PendingToolCall:
    return {
        "id": tool_call.id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
    }


async def agent_node(
    state: AgentState,
    runtime: Runtime[AgentRuntimeContext],
) -> dict[str, Any]:
    if state["turn"] >= MAX_AGENT_TURNS:
        raise AgentRunnerError("Agent turn limit reached.")

    turn = state["turn"] + 1
    callback = runtime.context.callback
    thought = callback.thought(turn)
    await callback.process(thought)
    answer_started = False
    reasoning = ""

    async def emit_reasoning_delta(delta: str) -> None:
        nonlocal reasoning
        if not delta or len(reasoning) >= MAX_REASONING_CHARS:
            return
        accepted = delta[: MAX_REASONING_CHARS - len(reasoning)]
        reasoning += accepted
        await callback.reasoning_delta(turn, accepted)

    def completed_thought(summary: str) -> dict[str, Any]:
        return {
            **thought,
            "status": "succeeded",
            "summary": summary,
            "reasoning": reasoning,
        }

    async def emit_answer_delta(delta: str) -> None:
        nonlocal answer_started
        if not delta:
            return
        if not answer_started:
            answer_started = True
            await callback.process(completed_thought("agent.answer_ready"))
        await callback.answer_delta(delta)

    model = runtime.context.model
    bound_model = model.bind_tools(runtime.context.tools) if runtime.context.tools else model
    if callback.enabled:
        aggregate: AIMessageChunk | None = None
        async for chunk in bound_model.astream(state["messages"]):
            if not isinstance(chunk, AIMessageChunk):
                raise AgentRunnerError("Agent model returned an invalid stream message.")
            await emit_reasoning_delta(reasoning_content(chunk))
            await emit_answer_delta(chunk.text)
            aggregate = chunk if aggregate is None else aggregate + chunk
        message = message_chunk_to_message(aggregate or AIMessageChunk(content=""))
    else:
        message = await bound_model.ainvoke(state["messages"])

    if not isinstance(message, AIMessage):
        raise AgentRunnerError("Agent model returned an invalid response message.")
    completion = model_completion(message)

    messages = [*state["messages"], message]
    tool_calls = [pending_tool_call(call) for call in completion.tool_calls]
    if tool_calls:
        await callback.process(completed_thought("agent.tools_selected"))
        return {
            "messages": messages,
            "turn": turn,
            "pending_tool_calls": tool_calls,
            "finish_reason": completion.finish_reason,
        }

    if completion.finish_reason == "length":
        raise AgentRunnerError("Agent response was truncated.")
    if not completion.content.strip():
        raise AgentRunnerError("Agent returned an empty response.")
    return {
        "messages": messages,
        "turn": turn,
        "pending_tool_calls": [],
        "finish_reason": completion.finish_reason,
        "final_answer": completion.content,
    }


def invalid_arguments_result() -> AgentToolResult:
    return AgentToolResult(
        content="Tool parameters are invalid.",
        summary="Invalid tool parameters.",
        is_error=True,
    )


async def execute_tool_call(
    prepared: PreparedToolCall,
    callback: NexaFlowCallback,
    turn: int,
) -> tuple[AgentToolResult, dict[str, Any]]:
    input_value = prepared.arguments or {}
    result = prepared.blocked_result
    if result is None:
        assert prepared.tool is not None
        await callback.process(
            callback.tool_event(
                turn=turn,
                tool_name=prepared.call["name"],
                call_id=prepared.call["id"],
                metadata=prepared.metadata,
                input_value=input_value,
            )
        )
        try:
            tool_output = await prepared.tool.ainvoke(input_value)
            result = (
                tool_output
                if isinstance(tool_output, AgentToolResult)
                else AgentToolResult(
                    content="Tool execution failed.",
                    summary="Tool execution failed.",
                    is_error=True,
                )
            )
        except Exception:
            result = AgentToolResult(
                content="Tool execution failed.",
                summary="Tool execution failed.",
                is_error=True,
            )

    event = callback.tool_event(
        turn=turn,
        tool_name=prepared.call["name"],
        call_id=prepared.call["id"],
        metadata=prepared.metadata,
        input_value=input_value,
        result=result,
    )
    await callback.process(event)
    return result, event


async def tool_node(
    state: AgentState,
    runtime: Runtime[AgentRuntimeContext],
) -> dict[str, Any]:
    calls = state["pending_tool_calls"]
    tool_call_count = state["tool_call_count"] + len(calls)
    if tool_call_count > MAX_AGENT_TOOL_CALLS:
        raise AgentRunnerError("Agent tool call limit reached.")

    tools = {tool.name: tool for tool in runtime.context.tools}
    callback = runtime.context.callback
    prepared_calls: list[PreparedToolCall] = []
    for call in calls:
        tool = tools.get(call["name"])
        metadata = (
            agent_tool_metadata(tool)
            if tool
            else {
                "display_name": call["name"],
                "kind": "unknown",
                "server_name": "",
            }
        )
        try:
            parsed_arguments = json.loads(call["arguments"])
        except (json.JSONDecodeError, TypeError):
            parsed_arguments = None

        if state["finish_reason"] == "length":
            blocked_result = AgentToolResult(
                content=(
                    "Tool call was not executed because the model response was truncated."
                ),
                summary="Truncated tool call rejected.",
                is_error=True,
            )
        elif tool is None:
            blocked_result = AgentToolResult(
                content=f"Tool {call['name']} is not available.",
                summary="Unknown tool rejected.",
                is_error=True,
            )
        elif not isinstance(parsed_arguments, dict):
            blocked_result = invalid_arguments_result()
        else:
            blocked_result = None
        prepared_calls.append(
            PreparedToolCall(
                call=call,
                tool=tool,
                metadata=metadata,
                arguments=(
                    parsed_arguments if isinstance(parsed_arguments, dict) else None
                ),
                blocked_result=blocked_result,
                parallel_safe=(
                    tool is not None
                    and blocked_result is None
                    and is_parallel_safe(tool)
                ),
            )
        )

    execution_results: dict[int, tuple[AgentToolResult, dict[str, Any]]] = {}
    index = 0
    while index < len(prepared_calls):
        prepared = prepared_calls[index]
        if not prepared.parallel_safe:
            execution_results[index] = await execute_tool_call(
                prepared,
                callback,
                state["turn"],
            )
            index += 1
            continue

        group_end = index + 1
        while (
            group_end < len(prepared_calls)
            and prepared_calls[group_end].parallel_safe
        ):
            group_end += 1
        group_results = await asyncio.gather(
            *(
                execute_tool_call(item, callback, state["turn"])
                for item in prepared_calls[index:group_end]
            )
        )
        for result_index, result in enumerate(group_results, start=index):
            execution_results[result_index] = result
        index = group_end

    messages = list(state["messages"])
    events = list(state["events"])
    seen_evidence_ids = set(state["seen_evidence_ids"])
    round_evidence_ids: set[str] = set()
    has_successful_retrieval = False
    no_new_evidence_rounds = state["no_new_evidence_rounds"]
    for index, prepared in enumerate(prepared_calls):
        result, event = execution_results[index]
        messages.append(tool_message(prepared.call, result))
        events.append(event)
        if prepared.metadata["kind"] == "knowledge" and not result.is_error:
            has_successful_retrieval = True
            round_evidence_ids.update(result.evidence_ids)

    if has_successful_retrieval:
        new_evidence_ids = round_evidence_ids - seen_evidence_ids
        if new_evidence_ids:
            seen_evidence_ids.update(new_evidence_ids)
            no_new_evidence_rounds = 0
        else:
            no_new_evidence_rounds += 1

    if no_new_evidence_rounds >= 2:
        messages.append(
            HumanMessage(
                content=(
                    "No new evidence found in two consecutive retrieval rounds. "
                    "Stop searching and answer with the available evidence."
                )
            )
        )
        no_new_evidence_rounds = 0

    return {
        "messages": messages,
        "events": events,
        "tool_call_count": tool_call_count,
        "seen_evidence_ids": sorted(seen_evidence_ids),
        "no_new_evidence_rounds": no_new_evidence_rounds,
        "pending_tool_calls": [],
    }


def route_after_agent(state: AgentState) -> Literal["tool", "__end__"]:
    return "tool" if state["pending_tool_calls"] else END


def build_agent_graph():
    graph = StateGraph(AgentState, context_schema=AgentRuntimeContext)
    graph.add_node("agent", agent_node)
    graph.add_node("tool", tool_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent)
    graph.add_edge("tool", "agent")
    return graph.compile(name="nexaflow_agent_runtime")


agent_graph = build_agent_graph()
