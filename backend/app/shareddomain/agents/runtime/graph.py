import asyncio
from copy import copy
import html
import json
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import aclosing
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
from langchain_core.utils.json import parse_partial_json
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.ports.llm import (
    ModelCompletion,
    ModelProviderError,
    ModelToolCall,
)
from app.shareddomain.agents.runtime.callbacks import NexaFlowCallback, safe_event_value
from app.shareddomain.agents.runtime.state import AgentState, PendingToolCall
from app.shareddomain.agents.runtime.tools import (
    AgentExecutionPaused,
    AgentToolResult,
    agent_tool_metadata,
    is_parallel_safe,
)
from app.shareddomain.agents.runtime.usage import merge_usage, usage_from_message

MAX_AGENT_TURNS = 8
MAX_AGENT_TOOL_CALLS = 12
MAX_REASONING_CHARS = 6000
MODEL_RESPONSE_TIMEOUT_SECONDS = 60
TOOL_RESPONSE_TIMEOUT_SECONDS = 30


class AgentRunnerError(ModelProviderError):
    pass


@dataclass(frozen=True)
class AgentRuntimeContext:
    model: BaseChatModel
    tools: list[StructuredTool]
    callback: NexaFlowCallback
    tool_timeout_seconds: float | None = None
    before_tool_call: Callable[
        [int, PendingToolCall, dict[str, str], dict[str, Any]],
        Awaitable[AgentToolResult | None],
    ] | None = None
    after_tool_call: Callable[
        [int, PendingToolCall, dict[str, str], dict[str, Any], AgentToolResult],
        Awaitable[None],
    ] | None = None
    max_turns: int = MAX_AGENT_TURNS
    max_tool_calls: int = MAX_AGENT_TOOL_CALLS
    max_model_tokens: int | None = None
    defer_answer: bool = False


@dataclass(frozen=True)
class PreparedToolCall:
    call: PendingToolCall
    tool: StructuredTool | None
    metadata: dict[str, str]
    arguments: dict[str, Any] | None
    blocked_result: AgentToolResult | None
    parallel_safe: bool


_DSML_TAG_RE = re.compile(
    r"<\s*(?P<closing>/?)\s*\|\s*DSML\s*\|\s*"
    r"(?P<slash>/?)\s*(?P<tag>function_calls|tool_calls|invoke|parameter)\b"
    r"(?P<attrs>[^>]*)>",
    re.IGNORECASE,
)
# Some Markdown renderers expand the two protocol separators to ``| |``.
_DSML_PREFIX_RE = re.compile(
    r"<\s*(?P<closing>/?)\s*\|\s*(?:\|\s*)?DSML\s*\|\s*(?:\|\s*)?",
    re.IGNORECASE,
)
_DSML_ANY_TAG_RE = re.compile(
    r"<\s*/?\s*\|\s*DSML\s*\|[^>]*>",
    re.IGNORECASE,
)
_DSML_MARKER_RE = re.compile(r"<\s*/?\s*\|\s*DSML\s*\|", re.IGNORECASE)
_DSML_MARKER_PREFIX = "<|dsml|"
_DSML_SPACED_MARKER_PREFIX = "<||dsml||"


def _canonicalize_dsml(text: str) -> str:
    return _DSML_PREFIX_RE.sub(
        lambda match: f"<{match.group('closing')}|DSML|",
        text,
    )


def _dsml_is_closing(match: re.Match[str]) -> bool:
    return bool(match.group("closing") or match.group("slash"))


def _dsml_attribute(attrs: str, name: str) -> str | None:
    pattern = rf"\b{re.escape(name)}\s*=\s*"
    match = re.search(pattern + r'"([^"]*)"', attrs, re.IGNORECASE)
    if match is None:
        match = re.search(pattern + r"'([^']*)'", attrs, re.IGNORECASE)
    if match is None:
        match = re.search(pattern + r"([^\s>]+)", attrs, re.IGNORECASE)
    if match is None:
        return None
    return html.unescape(match.group(1))


def _dsml_matching_tag(
    matches: list[re.Match[str]],
    start: int,
    tag: str,
) -> re.Match[str] | None:
    for match in matches[start:]:
        if match.group("tag").lower() != tag:
            continue
        # A few providers use the opening token for both sides of a tag.
        # The first same-name token is the close in both forms.
        return match
    return None


def _dsml_parameter_value(raw: str, string_value: str | None) -> Any:
    value = html.unescape(raw.strip())
    if string_value and string_value.lower() in {"false", "0", "no"}:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    if string_value is None and value[:1] in "[{":
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
    return value


def parse_dsml_tool_calls(text: str) -> tuple[str, tuple[ModelToolCall, ...]]:
    """Parse legacy text-mode DSML calls without exposing protocol markup."""
    if not isinstance(text, str):
        return text, ()

    normalized = _canonicalize_dsml(html.unescape(text))
    if _DSML_MARKER_RE.search(normalized) is None:
        return text, ()
    matches = list(_DSML_TAG_RE.finditer(normalized))
    calls: list[ModelToolCall] = []
    spans: list[tuple[int, int]] = []
    consumed_end = -1
    for index, invoke in enumerate(matches):
        if invoke.start() < consumed_end:
            continue
        if invoke.group("tag").lower() != "invoke" or _dsml_is_closing(invoke):
            continue
        close = _dsml_matching_tag(matches, index + 1, "invoke")
        body_end = close.start() if close is not None else len(normalized)
        body = normalized[invoke.end() : body_end]
        parameter_matches = list(_DSML_TAG_RE.finditer(body))
        arguments: dict[str, Any] = {}
        for parameter_index, parameter in enumerate(parameter_matches):
            if (
                parameter.group("tag").lower() != "parameter"
                or _dsml_is_closing(parameter)
            ):
                continue
            parameter_close = _dsml_matching_tag(
                parameter_matches,
                parameter_index + 1,
                "parameter",
            )
            value_end = (
                parameter_close.start()
                if parameter_close is not None
                else len(body)
            )
            name = _dsml_attribute(parameter.group("attrs"), "name")
            if name:
                arguments[name] = _dsml_parameter_value(
                    body[parameter.end() : value_end],
                    _dsml_attribute(parameter.group("attrs"), "string"),
                )
        name = _dsml_attribute(invoke.group("attrs"), "name")
        if name:
            calls.append(
                ModelToolCall(
                    id=f"dsml-{len(calls) + 1}",
                    name=name,
                    arguments=json.dumps(arguments, ensure_ascii=False),
                )
            )
        block_end = close.end() if close is not None else body_end
        spans.append((invoke.start(), block_end))
        consumed_end = block_end

    cleaned_parts: list[str] = []
    cursor = 0
    for start, end in spans:
        cleaned_parts.append(normalized[cursor:start])
        cursor = end
    cleaned_parts.append(normalized[cursor:])
    cleaned = _DSML_ANY_TAG_RE.sub("", "".join(cleaned_parts)).strip()
    return cleaned, tuple(calls)


def clean_model_text(text: str) -> str:
    return parse_dsml_tool_calls(text)[0]


def _partial_dsml_start(text: str) -> int | None:
    for index in range(max(0, len(text) - 32), len(text)):
        if text[index] != "<":
            continue
        compact = re.sub(r"\s+", "", text[index:]).lower()
        if compact.startswith("<") and any(
            prefix.startswith(compact)
            for prefix in (_DSML_MARKER_PREFIX, _DSML_SPACED_MARKER_PREFIX)
        ):
            return index
    return None


class ModelTextStreamFilter:
    """Hold a possible DSML marker until it is either confirmed or released."""

    def __init__(self) -> None:
        self._buffer = ""
        self._protocol = False

    def push(self, delta: str) -> str:
        if not isinstance(delta, str) or not delta:
            return ""
        if self._protocol:
            self._buffer += delta
            return ""
        combined = _canonicalize_dsml(self._buffer + delta)
        marker = _DSML_MARKER_RE.search(combined)
        if marker is not None:
            self._protocol = True
            self._buffer = combined[marker.start() :]
            return combined[: marker.start()]
        partial = _partial_dsml_start(combined)
        if partial is None:
            self._buffer = ""
            return combined
        self._buffer = combined[partial:]
        return combined[:partial]

    def finish(self) -> str:
        tail = self._buffer
        self._buffer = ""
        if not tail:
            return ""
        if self._protocol:
            return clean_model_text(tail)
        return "" if _partial_dsml_start(tail) is not None else tail


def partial_tool_input_preview(arguments: str) -> dict[str, str]:
    try:
        parsed = parse_partial_json(arguments)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    safe_value = safe_event_value(parsed, max_string_chars=None, max_list_items=None)
    if not isinstance(safe_value, dict):
        return {}
    preview: dict[str, str] = {}
    for raw_field, value in safe_value.items():
        field = str(raw_field)
        text = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, indent=2, default=str)
        )
        preview[field] = text
    return preview


def model_completion(message: AIMessage) -> ModelCompletion:
    tool_calls = [
        ModelToolCall(
            id=tool_call.get("id") or "",
            name=tool_call.get("name") or "",
            arguments=(
                tool_call.get("args")
                if isinstance(tool_call.get("args"), str)
                else json.dumps(tool_call.get("args") or {}, ensure_ascii=False)
            ),
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
    content, dsml_calls = parse_dsml_tool_calls(message.text)
    seen = {
        (
            call.name,
            json.dumps(
                _json_arguments(call.arguments),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        )
        for call in tool_calls
    }
    for call in dsml_calls:
        key = (
            call.name,
            json.dumps(
                _json_arguments(call.arguments),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        )
        if key not in seen:
            tool_calls.append(call)
            seen.add(key)
    finish_reason = message.response_metadata.get("finish_reason") or "stop"
    return ModelCompletion(
        content=content,
        tool_calls=tuple(tool_calls),
        finish_reason=str(finish_reason),
    )


def _json_arguments(arguments: Any) -> Any:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            return arguments
    return arguments


def sanitized_model_message(
    message: AIMessage,
    completion: ModelCompletion,
) -> AIMessage:
    tool_calls: list[dict[str, Any]] = []
    invalid_tool_calls: list[dict[str, Any]] = []
    for call in completion.tool_calls:
        arguments = _json_arguments(call.arguments)
        if isinstance(arguments, dict):
            tool_calls.append(
                {
                    "name": call.name,
                    "args": arguments,
                    "id": call.id,
                    "type": "tool_call",
                }
            )
        else:
            invalid_tool_calls.append(
                {
                    "name": call.name,
                    "args": call.arguments,
                    "id": call.id,
                    "error": None,
                    "type": "invalid_tool_call",
                }
            )
    update = {
        "content": completion.content,
        "tool_calls": tool_calls,
        "invalid_tool_calls": invalid_tool_calls,
    }
    model_copy = getattr(message, "model_copy", None)
    if callable(model_copy):
        return model_copy(update=update)
    # Workflow tests and lightweight provider adapters may expose only the
    # provider-neutral message attributes, not Pydantic's model_copy().
    try:
        fallback = copy(message)
        for key, value in update.items():
            setattr(fallback, key, value)
        if hasattr(fallback, "text"):
            fallback.text = completion.content
        return fallback
    except (AttributeError, TypeError):
        return AIMessage(**update)


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
    if state["turn"] >= runtime.context.max_turns:
        raise AgentRunnerError("Agent turn limit reached.")

    turn = state["turn"] + 1
    callback = runtime.context.callback
    thought = callback.thought(turn)
    await callback.process(thought)
    answer_started = False
    tool_call_started = False
    streamed_tool_calls: dict[int, dict[str, Any]] = {}
    reasoning = ""
    text_filter = ModelTextStreamFilter()

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
    allow_tools = turn < runtime.context.max_turns
    available_tools = runtime.context.tools
    if state["no_new_evidence_rounds"] >= 2:
        available_tools = [
            tool
            for tool in available_tools
            if agent_tool_metadata(tool)["kind"] != "knowledge"
        ]
    bound_model = (
        model.bind_tools(available_tools) if allow_tools and available_tools else model
    )
    try:
        if callback.enabled:
            async with aclosing(bound_model.astream(state["messages"])) as stream:
                aggregate: AIMessageChunk | None = None
                while True:
                    try:
                        async with asyncio.timeout(MODEL_RESPONSE_TIMEOUT_SECONDS):
                            chunk = await anext(stream)
                    except StopAsyncIteration:
                        break
                    if not isinstance(chunk, AIMessageChunk):
                        raise AgentRunnerError(
                            "Agent model returned an invalid stream message."
                        )
                    await emit_reasoning_delta(reasoning_content(chunk))
                    if chunk.tool_call_chunks:
                        if not tool_call_started:
                            tool_call_started = True
                            await callback.process(
                                {
                                    **thought,
                                    "status": "running",
                                    "summary": "agent.preparing_tool_call",
                                    "reasoning": reasoning,
                                }
                            )
                        for tool_chunk in chunk.tool_call_chunks:
                            raw_index = tool_chunk.get("index")
                            index = raw_index if isinstance(raw_index, int) else 0
                            streamed = streamed_tool_calls.setdefault(
                                index,
                                {
                                    "id": "",
                                    "name": "",
                                    "arguments": "",
                                    "preview": {},
                                    "announced": False,
                                },
                            )
                            for key in ("id", "name", "args"):
                                fragment = tool_chunk.get(key)
                                if not isinstance(fragment, str) or not fragment:
                                    continue
                                target = "arguments" if key == "args" else key
                                streamed[target] += fragment
                            call_id = str(streamed["id"])
                            tool_name = str(streamed["name"])
                            if not call_id or not tool_name:
                                continue
                            if not streamed["announced"]:
                                streamed["announced"] = True
                                await callback.process(
                                    callback.preparing_tool_event(
                                        turn=turn,
                                        tool_name=tool_name,
                                        call_id=call_id,
                                    )
                                )
                            preview = partial_tool_input_preview(
                                str(streamed["arguments"])
                            )
                            previous = streamed["preview"]
                            for field, value in preview.items():
                                prior = str(previous.get(field, ""))
                                if value == prior:
                                    continue
                                replace = bool(prior) and not value.startswith(prior)
                                delta = value if replace else value[len(prior) :]
                                await callback.tool_input_delta(
                                    turn=turn,
                                    call_id=call_id,
                                    tool_name=tool_name,
                                    field=field,
                                    delta=delta,
                                    replace=replace,
                                )
                            streamed["preview"] = preview
                    if chunk.text:
                        visible_text = text_filter.push(chunk.text)
                        if visible_text and not runtime.context.defer_answer:
                            await emit_answer_delta(visible_text)
                    aggregate = chunk if aggregate is None else aggregate + chunk
                trailing_text = text_filter.finish()
                if trailing_text and not runtime.context.defer_answer:
                    await emit_answer_delta(trailing_text)
                message = message_chunk_to_message(
                    aggregate or AIMessageChunk(content="")
                )
        else:
            async with asyncio.timeout(MODEL_RESPONSE_TIMEOUT_SECONDS):
                message = await bound_model.ainvoke(state["messages"])
    except TimeoutError as exc:
        raise AgentRunnerError("Agent model response timed out.") from exc

    if not isinstance(message, AIMessage):
        raise AgentRunnerError("Agent model returned an invalid response message.")
    completion = model_completion(message)
    message = sanitized_model_message(message, completion)

    messages = [*state["messages"], message]
    tool_calls = [pending_tool_call(call) for call in completion.tool_calls]
    model_usage = merge_usage(state["model_usage"], usage_from_message(message))
    if (
        runtime.context.max_model_tokens is not None
        and int(model_usage.get("total_tokens") or 0)
        > runtime.context.max_model_tokens
    ):
        raise AgentRunnerError("Agent model token limit reached.")
    if tool_calls and answer_started:
        await callback.answer_reset()
        answer_started = False
    if tool_calls:
        call_ids = [call["id"] for call in tool_calls]
        if any(not call_id for call_id in call_ids) or len(set(call_ids)) != len(
            call_ids
        ):
            raise AgentRunnerError("Agent model returned invalid tool call identifiers.")
        if not allow_tools:
            raise AgentRunnerError("Agent turn limit reached.")
        await callback.process(completed_thought("agent.tools_selected"))
        return {
            "messages": messages,
            "turn": turn,
            "pending_tool_calls": tool_calls,
            "finish_reason": completion.finish_reason,
            "model_usage": model_usage,
        }

    if completion.finish_reason == "length":
        raise AgentRunnerError("Agent response was truncated.")
    if not completion.content.strip():
        raise AgentRunnerError("Agent returned an empty response.")
    draft_answer = completion.content
    return {
        "messages": messages,
        "turn": turn,
        "pending_tool_calls": [],
        "finish_reason": completion.finish_reason,
        "draft_answer": draft_answer,
        "final_answer": draft_answer,
        "model_usage": model_usage,
    }


def invalid_arguments_result() -> AgentToolResult:
    return AgentToolResult(
        content="Tool parameters are invalid JSON; return a JSON object.",
        summary="Invalid tool parameters.",
        is_error=True,
    )


async def execute_tool_call(
    prepared: PreparedToolCall,
    callback: NexaFlowCallback,
    turn: int,
    timeout_seconds: float | None,
    runtime_context: AgentRuntimeContext | None = None,
) -> tuple[AgentToolResult, dict[str, Any]]:
    input_value = prepared.arguments or {}
    result = prepared.blocked_result
    started_at = time.perf_counter()
    if result is None:
        assert prepared.tool is not None
        if runtime_context is not None and runtime_context.before_tool_call is not None:
            result = await runtime_context.before_tool_call(
                turn,
                prepared.call,
                prepared.metadata,
                input_value,
            )
        if result is not None:
            event = callback.tool_event(
                turn=turn,
                tool_name=prepared.call["name"],
                call_id=prepared.call["id"],
                metadata=prepared.metadata,
                input_value=input_value,
                result=result,
            )
            event["duration_ms"] = round((time.perf_counter() - started_at) * 1000)
            await callback.process(event)
            return result, event
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
            async with asyncio.timeout(
                TOOL_RESPONSE_TIMEOUT_SECONDS
                if timeout_seconds is None
                else timeout_seconds
            ):
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
        except TimeoutError:
            result = AgentToolResult(
                content="Tool execution timed out.",
                summary="Tool execution timed out.",
                is_error=True,
                outcome_uncertain=(
                    prepared.metadata["kind"] == "mcp"
                    and prepared.metadata.get("policy_mode") != "read_only"
                ),
            )
        except AgentExecutionPaused:
            raise
        except Exception:
            result = AgentToolResult(
                content="Tool execution failed.",
                summary="Tool execution failed.",
                is_error=True,
                outcome_uncertain=(
                    prepared.metadata["kind"] == "mcp"
                    and prepared.metadata.get("policy_mode") != "read_only"
                ),
            )
        if runtime_context is not None and runtime_context.after_tool_call is not None:
            await runtime_context.after_tool_call(
                turn,
                prepared.call,
                prepared.metadata,
                input_value,
                result,
            )

    event = callback.tool_event(
        turn=turn,
        tool_name=prepared.call["name"],
        call_id=prepared.call["id"],
        metadata=prepared.metadata,
        input_value=input_value,
        result=result,
    )
    event["duration_ms"] = round((time.perf_counter() - started_at) * 1000)
    await callback.process(event)
    return result, event


async def tool_node(
    state: AgentState,
    runtime: Runtime[AgentRuntimeContext],
) -> dict[str, Any]:
    calls = state["pending_tool_calls"]
    tool_call_count = state["tool_call_count"] + len(calls)
    if tool_call_count > runtime.context.max_tool_calls:
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
        elif (
            state["no_new_evidence_rounds"] >= 2
            and agent_tool_metadata(tool)["kind"] == "knowledge"
        ):
            blocked_result = AgentToolResult(
                content=(
                    "Knowledge search stopped after two rounds without new evidence."
                ),
                summary="Knowledge search stopped after no new evidence.",
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
                runtime.context.tool_timeout_seconds,
                runtime.context,
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
                execute_tool_call(
                    item,
                    callback,
                    state["turn"],
                    runtime.context.tool_timeout_seconds,
                    runtime.context,
                )
                for item in prepared_calls[index:group_end]
            ),
            return_exceptions=True,
        )
        for result in group_results:
            if isinstance(result, BaseException):
                raise result
        for result_index, result in enumerate(group_results, start=index):
            execution_results[result_index] = result
        index = group_end

    messages = list(state["messages"])
    events = list(state["events"])
    seen_evidence_ids = set(state["seen_evidence_ids"])
    evidence_packets = list(state["evidence_packets"])
    round_evidence_ids: set[str] = set()
    has_retrieval_attempt = False
    no_new_evidence_rounds = state["no_new_evidence_rounds"]
    for index, prepared in enumerate(prepared_calls):
        result, event = execution_results[index]
        messages.append(tool_message(prepared.call, result))
        events.append(event)
        if prepared.metadata["kind"] == "knowledge":
            has_retrieval_attempt = True
            if not result.is_error:
                round_evidence_ids.update(result.evidence_ids)
                output = result.output
                if isinstance(output, dict) and isinstance(output.get("hits"), list):
                    for packet in output["hits"]:
                        if not isinstance(packet, dict):
                            continue
                        packet_id = packet.get("chunk_id")
                        if not isinstance(packet_id, str) or not packet_id:
                            continue
                        if any(
                            existing.get("chunk_id") == packet_id
                            for existing in evidence_packets
                        ):
                            continue
                        evidence_packets.append(packet)

    if has_retrieval_attempt:
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

    return {
        "messages": messages,
        "events": events,
        "tool_call_count": tool_call_count,
        "seen_evidence_ids": sorted(seen_evidence_ids),
        "evidence_packets": evidence_packets[:32],
        "no_new_evidence_rounds": no_new_evidence_rounds,
        "pending_tool_calls": [],
    }


def route_after_agent(state: AgentState) -> Literal["tool", "__end__"]:
    return "tool" if state["pending_tool_calls"] else END


def route_from_start(state: AgentState) -> Literal["agent", "tool"]:
    return "tool" if state["pending_tool_calls"] else "agent"


def build_agent_graph():
    graph = StateGraph(AgentState, context_schema=AgentRuntimeContext)
    graph.add_node("agent", agent_node)
    graph.add_node("tool", tool_node)
    graph.add_conditional_edges(START, route_from_start)
    graph.add_conditional_edges("agent", route_after_agent)
    graph.add_edge("tool", "agent")
    return graph.compile(name="nexaflow_agent_runtime")


agent_graph = build_agent_graph()
