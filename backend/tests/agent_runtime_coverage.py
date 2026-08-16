"""Runtime coverage suite for the Agent execution kernel.

Covers agent_executor / agent_runs / agent_memory / agent_tools, the
shareddomain runtime graph (executor, usage, tools, callbacks) and the Redis
live stream infrastructure. Pure-Python script suite (no pytest): run from
``backend/`` with ``uv run python -m tests.agent_runtime_coverage``.
"""

import asyncio
import dataclasses
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    message_to_dict,
)
from langchain_core.messages.tool import tool_call_chunk
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.support import (  # noqa: F401  (sets required env before app imports)
    activate_admin,
    auth_headers,
    settings as test_settings,
    test_client,
)

from app.application import agent_executor, agent_memory, agent_runs, agent_tools
from app.capabilities.llm.runtime import ModelCompletion, ModelToolCall
from app.entities.agents import Agent, AgentRun, AgentToolCall
from app.entities.knowledge import KnowledgeBase
from app.entities.tools import ApplicationToolBinding, McpServer, ToolSource
from app.infrastructure import agent_live_stream as live_stream_module
from app.infrastructure.config import Settings
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import mcp as mcp_repository
from app.infrastructure.repositories import tools as tool_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.session import get_session_factory
from app.infrastructure.model_utils import utc_now
from app.schemas.knowledge import (
    KnowledgeQueryHitResponse,
    KnowledgeQueryInspectResponse,
    KnowledgeRetrievalTraceResponse,
)
from app.shareddomain.agents.runtime import (
    AgentExecutionPaused,
    AgentRunnerError,
    AgentToolBusy,
    AgentToolResult,
    AgentToolUncertain,
    create_agent_tool,
    run_agent,
    safe_event_value,
)
from app.shareddomain.agents.runtime import graph as graph_module
from app.shareddomain.agents.runtime import executor as executor_module
from app.shareddomain.agents.runtime import usage as usage_module
from app.shareddomain.agents.runtime.usage import (
    add_compaction_usage,
    empty_usage,
    merge_usage,
    usage_from_message,
)
from app.shareddomain.tools.services import (
    ResolvedMcpTool,
    mcp_tool_definition_hash,
)
from app.shareddomain.tools.catalog import reconcile_mcp_discovery
from mcp.types import Tool as McpTool

MODEL_BASE_URL = "http://127.0.0.1:9"


def knowledge_inspect_result(
    knowledge_base: KnowledgeBase,
    payload,
    hits: list[KnowledgeQueryHitResponse] | None = None,
    rerank_status: str | None = None,
) -> KnowledgeQueryInspectResponse:
    resolved_hits = hits or []
    resolved_status = rerank_status or (
        "applied"
        if knowledge_base.reranker_model_id is not None and resolved_hits
        else (
            "skipped"
            if knowledge_base.reranker_model_id is not None
            else "not_configured"
        )
    )
    return KnowledgeQueryInspectResponse(
        hits=resolved_hits,
        trace=KnowledgeRetrievalTraceResponse(
            trace_id=f"trace-{knowledge_base.id}",
            search_mode=payload.search_mode,
            limit=payload.limit,
            min_similarity=payload.similarity,
            max_distance=(
                2 * (1 - payload.similarity)
                if payload.similarity is not None
                else None
            ),
            vector_candidates=len(resolved_hits),
            keyword_candidates=0,
            reference_candidates=0,
            fused_candidates=len(resolved_hits),
            rerank_status=resolved_status,
            returned_hits=len(resolved_hits),
            duration_ms=0,
            stage_duration_ms={},
        ),
    )


class AgentModelHandler(BaseHTTPRequestHandler):
    """Answers provider connectivity tests performed at model registration."""

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: [DONE]\n\n")
            return
        payload = {
            "id": "runtime-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "pong"},
                    "finish_reason": "stop",
                }
            ],
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, format: str, *args) -> None:
        return


@contextmanager
def agent_model_server() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), AgentModelHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def completion_message(completion: ModelCompletion) -> AIMessage:
    tool_calls = []
    invalid_tool_calls = []
    for call in completion.tool_calls:
        try:
            arguments = json.loads(call.arguments)
        except (json.JSONDecodeError, TypeError):
            arguments = None
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
    return AIMessage(
        content=completion.content,
        tool_calls=tool_calls,
        invalid_tool_calls=invalid_tool_calls,
        response_metadata={"finish_reason": completion.finish_reason},
    )


class SequenceProvider:
    """ainvoke stub: pops one completion per call."""

    def __init__(self, completions: list[ModelCompletion]) -> None:
        self.completions = list(completions)
        self.requests: list[list[BaseMessage]] = []

    def bind_tools(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.requests.append(list(messages))
        return completion_message(self.completions.pop(0))


class StreamingProvider(SequenceProvider):
    """astream stub mirroring the graph's streaming path."""

    def __init__(
        self,
        completions: list[ModelCompletion],
        reasoning: list[list[str]] | None = None,
    ) -> None:
        super().__init__(completions)
        self.reasoning = reasoning or [[] for _ in completions]

    async def astream(self, messages: list[BaseMessage]):
        self.requests.append(list(messages))
        completion = self.completions.pop(0)
        for delta in self.reasoning.pop(0):
            yield AIMessageChunk(
                content="",
                additional_kwargs={"reasoning_content": delta},
            )
        for index, call in enumerate(completion.tool_calls):
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    tool_call_chunk(
                        name=call.name,
                        args=call.arguments,
                        id=call.id,
                        index=index,
                    )
                ],
            )
        if completion.content:
            yield AIMessageChunk(content=completion.content)
        yield AIMessageChunk(
            content="",
            response_metadata={"finish_reason": completion.finish_reason},
        )


class RuntimeModelStub:
    """Durable-run model stub: astream for graph turns, ainvoke for compaction."""

    def __init__(
        self,
        completions: list[ModelCompletion],
        invoke_error: Exception | None = None,
    ) -> None:
        self.completions = list(completions)
        self.invoke_error = invoke_error
        self.requests: list[list[BaseMessage]] = []
        self.profile = {"max_input_tokens": 65536}

    def bind_tools(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.requests.append(list(messages))
        if self.invoke_error is not None:
            raise self.invoke_error
        return AIMessage(
            content="Compacted durable summary of earlier turns.",
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
        )

    async def astream(self, messages: list[BaseMessage]):
        self.requests.append(list(messages))
        completion = self.completions.pop(0)
        for index, call in enumerate(completion.tool_calls):
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    tool_call_chunk(
                        name=call.name,
                        args=call.arguments,
                        id=call.id,
                        index=index,
                    )
                ],
            )
        if completion.content:
            yield AIMessageChunk(content=completion.content)
        yield AIMessageChunk(
            content="",
            response_metadata={"finish_reason": completion.finish_reason},
        )


class HangingStreamingProvider:
    def bind_tools(self, *_args, **_kwargs):
        return self

    async def astream(self, _messages: list[BaseMessage]):
        await asyncio.Event().wait()
        yield AIMessageChunk(content="")


def ok_completion(content: str = "Done.") -> ModelCompletion:
    return ModelCompletion(content=content, tool_calls=(), finish_reason="stop")


def tool_completion(name: str, call_id: str, arguments: str = "{}") -> ModelCompletion:
    return ModelCompletion(
        content="",
        tool_calls=(ModelToolCall(call_id, name, arguments),),
        finish_reason="tool_calls",
    )


# ---------------------------------------------------------------------------
# Pure unit tests (no database)
# ---------------------------------------------------------------------------


def assert_usage_normalization() -> None:
    usage = empty_usage()
    assert usage["model_calls"] == 0 and usage["total_tokens"] == 0
    assert usage["compaction"]["input_tokens"] == 0

    def raw_message(usage_metadata=None, response_metadata=None) -> Any:
        # raw attribute holder: langchain AIMessage would normalize these
        # values, so exercise the provider-neutral normalization directly.
        return SimpleNamespace(
            usage_metadata=usage_metadata,
            response_metadata=response_metadata or {},
        )

    # bool values are not numbers (usage.py:29)
    record = usage_from_message(
        raw_message(
            {
                "input_tokens": True,
                "output_tokens": 5,
                "total_tokens": 15,
            }
        )
    )
    assert record["input_tokens"] == 0 and record["output_tokens"] == 5
    assert record["reported_model_calls"] == 1

    # integral float (usage.py:33) and numeric string (usage.py:35)
    record = usage_from_message(
        raw_message({"total_tokens": 12.0, "input_tokens": "7"})
    )
    assert record["total_tokens"] == 12 and record["input_tokens"] == 7

    # total computed from parts when absent (usage.py:81)
    record = usage_from_message(
        raw_message(
            response_metadata={"usage": {"prompt_tokens": 10, "completion_tokens": 3}}
        )
    )
    assert record["total_tokens"] == 13
    assert record["reported_model_calls"] == 1

    # cache creation surfaced into input details (usage.py:100)
    record = usage_from_message(
        raw_message(
            {
                "input_token_details": {"cache_creation": 4},
                "output_token_details": {"reasoning": 2},
            }
        )
    )
    assert record["cache_creation_input_tokens"] == 4
    assert record["input_token_details"]["cache_creation"] == 4
    assert record["output_token_details"]["reasoning"] == 2

    # cache read via legacy key names and response-level token usage
    record = usage_from_message(
        raw_message(
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 6,
                    "completion_tokens": 2,
                    "cache_read": 3,
                    "cache_creation": 1,
                }
            }
        )
    )
    assert record["input_tokens"] == 6 and record["output_tokens"] == 2
    assert record["cache_read_input_tokens"] == 3
    assert record["input_token_details"]["cache_read"] == 3
    assert record["input_token_details"]["cache_creation"] == 1

    # no usage reported at all
    record = usage_from_message(raw_message())
    assert record["reported_model_calls"] == 0

    # merging sums numbers and keeps non-numeric values (usage.py:126-127)
    merged = merge_usage(
        {"input_tokens": 3, "label": "first"},
        {"input_tokens": 4, "output_tokens": 1},
    )
    assert merged["input_tokens"] == 7
    assert merged["output_tokens"] == 1
    assert merged["label"] == "first"

    # nested compaction accounting
    total = add_compaction_usage(
        {"input_tokens": 9},
        {"input_tokens": 5, "output_tokens": 3},
    )
    assert total["input_tokens"] == 14
    assert total["compaction"]["input_tokens"] == 5
    assert total["compaction"]["output_tokens"] == 3


def assert_agent_tool_construction() -> None:
    # schema that fails check_schema (tools.py:62-63)
    for invalid in (
        {"type": "object", "properties": 42},
        {"type": "object", "required": "nope"},
    ):
        try:
            create_agent_tool(
                name="bad",
                description="bad",
                parameters=invalid,
                execute=lambda _arguments: None,
            )
        except ValueError as exc:
            assert str(exc) == "Tool schema is invalid."
        else:
            raise AssertionError("Invalid tool schema was accepted.")

    # non-object schema (tools.py:65)
    try:
        create_agent_tool(
            name="bad",
            description="bad",
            parameters={"type": "array"},
            execute=lambda _arguments: None,
        )
    except ValueError as exc:
        assert str(exc) == "Tool schema must describe an object."
    else:
        raise AssertionError("Non-object tool schema was accepted.")

    # exception constructors (tools.py:41)
    busy = AgentToolBusy("call-busy", "another worker owns it")
    assert busy.call_id == "call-busy" and busy.reason == "another worker owns it"
    uncertain = AgentToolUncertain("call-uncertain", "outcome unknown")
    assert uncertain.call_id == "call-uncertain"
    paused = AgentExecutionPaused("call-paused", "needs approval")
    assert paused.call_id == "call-paused"

    # valid tool with schema validation on invoke
    async def execute(arguments: str) -> AgentToolResult:
        return AgentToolResult(content=arguments, summary="ok")

    tool = create_agent_tool(
        name="echo",
        description="Echo",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        execute=execute,
        display_name="Echo Tool",
        kind="custom",
        server_name="srv",
        parallel_safe=True,
        policy_mode="read_only",
        server_id="server-1",
        definition_hash="def-1",
        source_tool_name="echo",
    )
    assert tool.name == "echo"
    metadata = tool.metadata or {}
    assert metadata["kind"] == "custom" and metadata["parallel_safe"] is True
    from app.shareddomain.agents.runtime.tools import (
        agent_tool_metadata,
        is_parallel_safe,
    )

    assert agent_tool_metadata(tool)["kind"] == "custom"
    assert agent_tool_metadata(tool)["source_tool_name"] == "echo"
    assert is_parallel_safe(tool) is True


def assert_callback_safety() -> None:
    # redaction of sensitive fields
    assert safe_event_value({"password": "hunter2"}, "password") == "[REDACTED]"
    assert safe_event_value("my secret token", "authorization") == "[REDACTED]"
    # string truncation
    long_text = "x" * 5000
    assert len(safe_event_value(long_text)) == 2000
    # list truncation and recursion
    values = safe_event_value([{"api_key": "k"}] * 30)
    assert len(values) == 20
    assert values[0]["api_key"] == "[REDACTED]"
    # dict truncation
    big = {str(index): index for index in range(50)}
    assert len(safe_event_value(big)) == 20
    # scalar passthrough
    assert safe_event_value(None) is None
    assert safe_event_value(True) is True
    assert safe_event_value(1.5) == 1.5
    # arbitrary object coerced to truncated string (callbacks.py:35)
    rendered = safe_event_value({"key": object()})
    assert isinstance(rendered["key"], str)
    assert len(rendered["key"]) <= 2000


async def checkpoint_state(**overrides: Any) -> dict[str, Any]:
    state = {
        "messages": [message_to_dict(HumanMessage(content="hi"))],
        "events": [],
        "turn": 0,
        "tool_call_count": 0,
        "seen_evidence_ids": [],
        "no_new_evidence_rounds": 0,
        "pending_tool_calls": [],
        "finish_reason": "",
        "final_answer": "",
        "model_usage": {},
    }
    state.update(overrides)
    return state


def assert_graph_error_branches() -> None:
    async def emit(_event: dict) -> None:
        return None

    async def run_turn_limit() -> None:
        await run_agent(
            SequenceProvider([ok_completion()]),
            [{"role": "user", "content": "hi"}],
            [],
            checkpoint=await checkpoint_state(turn=9),
        )

    try:
        asyncio.run(run_turn_limit())
    except AgentRunnerError as exc:
        assert "turn limit" in str(exc)
    else:
        raise AssertionError("Turn limit was not enforced.")

    async def run_last_turn_tool_call() -> None:
        # turn 8 is allowed, turn 9 removes tools; a tool call on the last
        # turn must raise the turn-limit error (graph.py:201-202).
        await run_agent(
            SequenceProvider([tool_completion("echo", "call-last")]),
            [{"role": "user", "content": "hi"}],
            [create_echo_tool()],
            checkpoint=await checkpoint_state(turn=8, tool_call_count=8),
        )

    try:
        asyncio.run(run_last_turn_tool_call())
    except AgentRunnerError as exc:
        assert "turn limit" in str(exc)
    else:
        raise AssertionError("Tool call on final turn was accepted.")

    async def run_truncated() -> None:
        await run_agent(
            SequenceProvider(
                [ModelCompletion(content="partial", tool_calls=(), finish_reason="length")]
            ),
            [{"role": "user", "content": "hi"}],
            [],
        )

    try:
        asyncio.run(run_truncated())
    except AgentRunnerError as exc:
        assert "truncated" in str(exc)
    else:
        raise AssertionError("Truncated response was accepted.")

    async def run_empty() -> None:
        await run_agent(
            SequenceProvider([ModelCompletion(content="   ", tool_calls=(), finish_reason="stop")]),
            [{"role": "user", "content": "hi"}],
            [],
        )

    try:
        asyncio.run(run_empty())
    except AgentRunnerError as exc:
        assert "empty response" in str(exc)
    else:
        raise AssertionError("Empty response was accepted.")

    async def run_invalid_message_type() -> None:
        class WrongTypeProvider(SequenceProvider):
            async def ainvoke(self, messages: list[BaseMessage]) -> BaseMessage:
                self.requests.append(list(messages))
                return HumanMessage(content="not an assistant message")

        await run_agent(
            WrongTypeProvider([]),
            [{"role": "user", "content": "hi"}],
            [],
        )

    try:
        asyncio.run(run_invalid_message_type())
    except AgentRunnerError as exc:
        assert "invalid response" in str(exc)
    else:
        raise AssertionError("Non-assistant model response was accepted.")

    async def run_invalid_stream_chunk() -> None:
        class BadChunkProvider(SequenceProvider):
            async def astream(self, messages: list[BaseMessage]):
                self.requests.append(list(messages))
                yield HumanMessage(content="wrong chunk type")

        await run_agent(
            BadChunkProvider([]),
            [{"role": "user", "content": "hi"}],
            [],
            on_event=emit,
        )

    try:
        asyncio.run(run_invalid_stream_chunk())
    except AgentRunnerError as exc:
        assert "invalid stream message" in str(exc)
    else:
        raise AssertionError("Invalid stream chunk was accepted.")

    async def run_pause_passthrough() -> None:
        async def execute(_arguments: str) -> AgentToolResult:
            raise AgentExecutionPaused("call-pause", "needs approval")

        tool = create_agent_tool(
            name="pause_tool",
            description="Pause",
            parameters={"type": "object", "properties": {}},
            execute=execute,
            kind="mcp",
            policy_mode="approval_required",
        )
        await run_agent(
            SequenceProvider([tool_completion("pause_tool", "call-pause"), ok_completion()]),
            [{"role": "user", "content": "hi"}],
            [tool],
        )

    try:
        asyncio.run(run_pause_passthrough())
    except AgentExecutionPaused as exc:
        assert exc.call_id == "call-pause"
    else:
        raise AssertionError("AgentExecutionPaused was swallowed.")

    async def run_unknown_tool() -> None:
        events: list[dict] = []

        async def record(event: dict) -> None:
            events.append(event)

        result = await run_agent(
            StreamingProvider(
                [tool_completion("missing_tool", "call-missing"), ok_completion()]
            ),
            [{"role": "user", "content": "hi"}],
            [create_echo_tool()],
            on_event=record,
        )
        assert result.content == "Done."
        tool_events = [
            event["event"]
            for event in events
            if event.get("type") == "process" and event["event"].get("type") == "tool"
        ]
        assert any(
            event["call_id"] == "call-missing" and event["status"] == "failed"
            for event in tool_events
        )
        failed = next(
            event for event in tool_events if event["call_id"] == "call-missing"
        )
        assert failed["summary"] == "Unknown tool rejected."

    asyncio.run(run_unknown_tool())

    async def run_knowledge_stop() -> None:
        events: list[dict] = []

        async def record(event: dict) -> None:
            events.append(event)

        async def retrieve(_arguments: str) -> AgentToolResult:
            raise AssertionError("knowledge tool must not execute")

        knowledge_tool = create_agent_tool(
            name="search_knowledge",
            description="Search",
            parameters={"type": "object", "properties": {}},
            execute=retrieve,
            kind="knowledge",
        )
        result = await run_agent(
            StreamingProvider([ok_completion()]),
            [{"role": "user", "content": "hi"}],
            [knowledge_tool],
            checkpoint=await checkpoint_state(
                turn=1,
                tool_call_count=1,
                no_new_evidence_rounds=2,
                pending_tool_calls=[
                    {"id": "call-knowledge", "name": "search_knowledge", "arguments": "{}"}
                ],
                finish_reason="tool_calls",
            ),
            on_event=record,
        )
        assert result.content == "Done."
        tool_events = [
            event["event"]
            for event in events
            if event.get("type") == "process" and event["event"].get("type") == "tool"
        ]
        assert any(
            event["call_id"] == "call-knowledge"
            and event["summary"] == "Knowledge search stopped after no new evidence."
            for event in tool_events
        )

    asyncio.run(run_knowledge_stop())


def create_echo_tool() -> Any:
    async def execute(arguments: str) -> AgentToolResult:
        return AgentToolResult(content=f"echo:{arguments}", summary="ok")

    return create_agent_tool(
        name="echo",
        description="Echo tool",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
        execute=execute,
    )


def assert_executor_checkpoint_paths() -> None:
    # checkpoint carrying a final answer short-circuits (executor.py:103)
    async def run_resumed() -> None:
        provider = SequenceProvider([ok_completion()])
        result = await run_agent(
            provider,
            [{"role": "user", "content": "hi"}],
            [],
            checkpoint=await checkpoint_state(
                messages=[message_to_dict(HumanMessage(content="hi"))],
                events=[{"type": "process", "event": {"status": "succeeded"}}],
                turn=2,
                tool_call_count=1,
                seen_evidence_ids=["chunk-1"],
                finish_reason="stop",
                final_answer="already answered",
                model_usage={"model_calls": 1},
            ),
        )
        assert result.content == "already answered"
        assert result.events == [{"type": "process", "event": {"status": "succeeded"}}]
        assert result.model_usage["model_calls"] == 1
        assert provider.requests == []

    asyncio.run(run_resumed())

    # serialize/deserialize round-trip and initial checkpoint callback
    async def run_with_checkpoints() -> None:
        phases: list[str] = []
        saved: list[dict[str, Any]] = []

        async def on_checkpoint(checkpoint: dict[str, Any], phase: str) -> None:
            phases.append(phase)
            saved.append(checkpoint)

        result = await run_agent(
            StreamingProvider([ok_completion("final")]),
            [{"role": "user", "content": "hi"}],
            [],
            on_checkpoint=on_checkpoint,
        )
        assert result.content == "final"
        assert phases[0] == "agent"
        assert phases[-1] == "done"
        assert saved[0]["turn"] == 0
        restored = executor_module.deserialize_agent_state(saved[-1])
        assert restored["final_answer"] == "final"

    asyncio.run(run_with_checkpoints())


def assert_ledger_pure_helpers() -> None:
    from app.application.agent_executor import (
        _arguments_hash,
        _stored_tool_result,
        current_mcp_policy_mode,
    )

    assert _arguments_hash({"b": 1, "a": 2}) == _arguments_hash({"a": 2, "b": 1})
    assert _arguments_hash({"a": 2}) != _arguments_hash({"a": 3})

    rejected = AgentToolCall(status="rejected")
    result = _stored_tool_result(rejected)
    assert result.is_error and result.content == "Tool call was rejected by the user."

    succeeded = AgentToolCall(
        status="succeeded",
        result_content="ok",
        result_summary="summary",
        result_output={"x": 1},
        result_is_error=False,
        result_evidence_ids=["c1", "c2"],
    )
    result = _stored_tool_result(succeeded)
    assert not result.is_error
    assert result.content == "ok" and result.output == {"x": 1}
    assert result.evidence_ids == frozenset({"c1", "c2"})

    metadata = {
        "policy_mode": "read_only",
        "definition_hash": "def-hash",
    }
    policy = SimpleNamespace(mode="read_only", definition_hash="def-hash")
    # api: verified read-only policy with matching hashes (line 173)
    assert (
        current_mcp_policy_mode("api", metadata, policy, "def-hash") == "read_only"
    )
    # api: drifted definition is disabled (line 174)
    assert (
        current_mcp_policy_mode("api", metadata, policy, "other-hash") == "disabled"
    )
    assert current_mcp_policy_mode("api", metadata, None, "def-hash") == "disabled"
    # console: no policy -> stored metadata mode (line 176)
    assert current_mcp_policy_mode("console", metadata, None) == "read_only"
    # explicit disable is authoritative (line 180)
    assert (
        current_mcp_policy_mode(
            "console", metadata, SimpleNamespace(mode="disabled"), "def-hash"
        )
        == "disabled"
    )
    # policy hash drift requires approval (line 182)
    assert (
        current_mcp_policy_mode(
            "console",
            metadata,
            SimpleNamespace(mode="read_only", definition_hash="stale"),
        )
        == "approval_required"
    )
    # live definition drift requires renewed approval (line 189)
    assert (
        current_mcp_policy_mode(
            "console",
            {"policy_mode": "read_only", "definition_hash": "old"},
            SimpleNamespace(mode="read_only", definition_hash="old"),
            "new-hash",
        )
        == "approval_required"
    )
    # unchanged policy mode is returned (line 190)
    assert (
        current_mcp_policy_mode(
            "console",
            {"policy_mode": "read_only", "definition_hash": "def-hash"},
            SimpleNamespace(mode="read_only", definition_hash="def-hash"),
            "def-hash",
        )
        == "read_only"
    )


def assert_live_stream_degradation() -> None:
    class FakePipeline:
        def __init__(self, error: Exception | None = None) -> None:
            self.error = error
            self.operations: list[tuple] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        def xadd(self, *args, **kwargs):
            self.operations.append(("xadd", args, kwargs))
            return self

        def expire(self, *args, **kwargs):
            self.operations.append(("expire", args, kwargs))
            return self

        async def execute(self):
            if self.error is not None:
                raise self.error
            return []

    class FakePublishRedis:
        def __init__(self, error: Exception | None = None) -> None:
            self.error = error
            self.closed = False
            self.last_pipeline: FakePipeline | None = None

        def pipeline(self, transaction: bool = False):
            self.last_pipeline = FakePipeline(self.error)
            return self.last_pipeline

        async def aclose(self):
            self.closed = True

    async def run() -> None:
        settings = test_settings()

        original = live_stream_module._redis_client
        try:
            live_stream_module._redis_client = (
                lambda _settings: FakePublishRedis()
            )
            publisher = live_stream_module.AgentLiveStreamPublisher(
                settings, "run-live"
            )
            await publisher.publish(
                {"type": "answer_delta", "delta": "hello"}
            )
            assert publisher._available
            # non-live event types are dropped without touching redis
            await publisher.publish({"type": "process", "event": {}})
            assert publisher._available
            await publisher.close()

            live_stream_module._redis_client = (
                lambda _settings: FakePublishRedis(error=RedisError("down"))
            )
            publisher = live_stream_module.AgentLiveStreamPublisher(
                settings, "run-live-2"
            )
            await publisher.publish({"type": "answer_delta", "delta": "x"})
            assert not publisher._available
            # once unavailable, publish short-circuits
            await publisher.publish({"type": "answer_delta", "delta": "y"})
            assert not publisher._available
            await publisher.close()

            live_stream_module._redis_client = (
                lambda _settings: FakePublishRedis(error=OSError("refused"))
            )
            publisher = live_stream_module.AgentLiveStreamPublisher(
                settings, "run-live-3"
            )
            await publisher.publish({"type": "reasoning_delta", "turn": 1, "delta": "z"})
            assert not publisher._available
            await publisher.close()

            # reader: unavailable short-circuit (line 87)
            reader = live_stream_module.AgentLiveStreamReader(settings, "run-live-4")
            reader._available = False
            assert await reader.read(None, 100) == []
            await reader.close()

            # reader: redis error degrades and returns empty (95-97, 102)
            class ErrorRedis:
                async def xread(self, *_args, **_kwargs):
                    raise TimeoutError("redis timeout")

                async def aclose(self):
                    return None

            live_stream_module._redis_client = lambda _settings: ErrorRedis()
            reader = live_stream_module.AgentLiveStreamReader(settings, "run-live-5")
            assert await reader.read(None, 100) == []
            assert not reader.available
            await reader.close()

            # reader: skips malformed payloads (108, 111-112), keeps valid ones
            class PayloadRedis:
                async def xread(self, *_args, **_kwargs):
                    return [
                        (
                            "nexaflow:agent-live:run-live-6",
                            [
                                (
                                    "1700000000000-0",
                                    {"payload": b"not-a-string"},
                                ),
                                (
                                    "1700000000000-1",
                                    {"payload": "{not json"},
                                ),
                                (
                                    "1700000000000-2",
                                    {"payload": json.dumps({"type": "answer_delta", "delta": "ok"})},
                                ),
                                (
                                    "1700000000000-3",
                                    {"payload": json.dumps({"type": "process"})},
                                ),
                            ],
                        )
                    ]

                async def aclose(self):
                    return None

            live_stream_module._redis_client = lambda _settings: PayloadRedis()
            reader = live_stream_module.AgentLiveStreamReader(settings, "run-live-6")
            entries = await reader.read(None, 100)
            assert entries == [("1700000000000-2", {"type": "answer_delta", "delta": "ok"})]
            await reader.close()
        finally:
            live_stream_module._redis_client = original

    asyncio.run(run())


def assert_event_replay_cursor_error() -> None:
    async def run() -> None:
        original = agent_executor.agent_repository.list_agent_run_events

        async def stuck_page(_db, _run_id, after=0, limit=200):
            return [SimpleNamespace(id=1) for _ in range(500)]

        agent_executor.agent_repository.list_agent_run_events = stuck_page
        try:
            await agent_executor._list_all_agent_run_events(None, "run-1")
        except AgentRunnerError as exc:
            assert "cursor did not advance" in str(exc)
        else:
            raise AssertionError("Stuck replay cursor was not detected.")
        finally:
            agent_executor.agent_repository.list_agent_run_events = original

    asyncio.run(run())


def assert_memory_pure_functions() -> None:
    from app.application.agent_memory import (
        _configured_context_window,
        _fit_memory,
        _message_text,
        _run_messages,
        _summary_source,
        _trim_pair_to_budget,
    )

    # _run_messages: non-succeeded runs produce no messages (line 41)
    failed = AgentRun(status="failed", goal="q", result="a")
    assert _run_messages(failed) == []
    # missing goal or answer (line 45)
    empty = AgentRun(status="succeeded", goal="q", result="")
    assert _run_messages(empty) == []
    # attachment context is prepended
    attached = AgentRun(
        status="succeeded",
        goal="question",
        result="answer",
        attachment_context="file text",
    )
    messages = _run_messages(attached)
    assert len(messages) == 2
    assert "file text" in messages[0]["content"]

    # _trim_pair_to_budget: budget too small (line 136)
    pair = [{"role": "user", "content": "hello world"}, {"role": "assistant", "content": "hi"}]
    assert _trim_pair_to_budget(pair, 1) == []
    trimmed = _trim_pair_to_budget(pair, 40)
    assert sum(len(message["content"]) for message in trimmed) <= 40

    # _fit_memory: non-positive budget (line 157)
    assert _fit_memory("", [], 0) == []
    # skipped runs (line 163) and empty selection (line 186)
    assert _fit_memory("", [AgentRun(status="queued")], 100) == []
    # summary alone exceeds a tiny budget -> empty selection path (line 186)
    assert _fit_memory("a long summary that cannot fit", [], 10) == []
    # summary included when it fits the budget
    fitted = _fit_memory(
        "prior summary",
        [AgentRun(status="succeeded", goal="g", result="r")],
        500,
    )
    assert fitted and fitted[0]["role"] == "user"
    assert "prior summary" in fitted[0]["content"]
    assert fitted[-1]["role"] == "assistant"

    # _summary_source with existing summary (line 192)
    source = _summary_source("old", [AgentRun(status="succeeded", goal="g", result="r")])
    assert source[0]["content"].startswith("Existing summary")
    assert source[-1]["role"] == "assistant"

    # _configured_context_window: bool candidate skipped (line 111), default (118)
    model = SimpleNamespace(meta={"context_window_tokens": True})
    assert _configured_context_window(model, SimpleNamespace(profile={})) == 32768
    # valid candidate wins
    model = SimpleNamespace(meta={"context_window_tokens": 8192})
    assert _configured_context_window(model, SimpleNamespace(profile={})) == 8192
    # chat profile fallback
    model = SimpleNamespace(meta={})
    chat_model = SimpleNamespace(profile={"max_input_tokens": 16384})
    assert _configured_context_window(model, chat_model) == 16384
    # oversized values are capped at 2M
    model = SimpleNamespace(meta={"context_window": 3_000_000})
    assert _configured_context_window(model, SimpleNamespace(profile={})) == 2_000_000

    # _message_text content variants (lines 206-214)
    assert _message_text(AIMessage(content=" plain ")) == "plain"
    assert _message_text(SimpleNamespace(content=["a", {"text": "b"}, 3])) == "ab"
    assert _message_text(SimpleNamespace(content=None)) == ""
    assert _message_text(SimpleNamespace(content=42)) == "42"


# ---------------------------------------------------------------------------
# Database-backed tests (fresh in-memory DB per test_client block)
# ---------------------------------------------------------------------------


def model_payload(
    name: str,
    model_type: str = "LLM",
    meta: dict | None = None,
    api_base: str = MODEL_BASE_URL,
) -> dict:
    return {
        "name": name,
        "provider": "model_deepseek_provider",
        "provider_type": "deepseek",
        "model_type": model_type,
        "model_name": "deepseek-chat",
        "credential": {"api_base": api_base, "api_key": "sk-runtime-test-1234"},
        "meta": meta or {},
    }


async def db_setup(
    client,
    admin_token: str,
    workspace_id: str,
    model_base_url: str,
) -> dict[str, Any]:
    model = client.post(
        f"/api/v1/workspaces/{workspace_id}/models",
        headers=auth_headers(admin_token),
        json=model_payload(
            "Runtime LLM",
            meta={"context_window_tokens": 32768},
            api_base=model_base_url,
        ),
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]

    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token))
    assert me.status_code == 200, me.text
    admin_user_id = me.json()["user"]["id"]

    # RERANKER model inserted directly: the API would run a live provider test.
    from app.capabilities.llm.models import RegisteredModel as RegisteredModelORM
    from app.infrastructure.model_utils import new_id

    async with get_session_factory()() as db:
        reranker_orm = RegisteredModelORM(
            id=new_id(),
            workspace_id=workspace_id,
            name="Runtime Reranker",
            provider="model_custom_provider",
            provider_type="openai_compatible",
            api_base=model_base_url,
            model_type="RERANKER",
            model_name="BAAI/bge-reranker-v2-m3",
            status="active",
            meta={},
            created_by_user_id=admin_user_id,
        )
        db.add(reranker_orm)
        await db.commit()
        reranker_id = reranker_orm.id

    knowledge_base = client.post(
        f"/api/v1/workspaces/{workspace_id}/knowledge-bases",
        headers=auth_headers(admin_token),
        json={"name": "Runtime Docs", "description": "Runtime knowledge"},
    )
    assert knowledge_base.status_code == 201, knowledge_base.text
    knowledge_base_id = knowledge_base.json()["id"]

    rerank_kb = client.post(
        f"/api/v1/workspaces/{workspace_id}/knowledge-bases",
        headers=auth_headers(admin_token),
        json={
            "name": "Reranked Docs",
            "description": "Reranked knowledge",
            "reranker_model_id": reranker_id,
        },
    )
    assert rerank_kb.status_code == 201, rerank_kb.text
    rerank_kb_id = rerank_kb.json()["id"]

    created = client.post(
        f"/api/v1/workspaces/{workspace_id}/agents",
        headers=auth_headers(admin_token),
        json={
            "name": "Runtime Agent",
            "description": "Runtime coverage agent",
            "instructions": "Answer directly.",
            "model_id": model_id,
            "knowledge_base_ids": [knowledge_base_id],
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    workflow_agent = client.post(
        f"/api/v1/workspaces/{workspace_id}/agents",
        headers=auth_headers(admin_token),
        json={
            "name": "Runtime Workflow",
            "instructions": "Follow the steps.",
            "model_id": model_id,
            "app_type": "workflow",
        },
    )
    assert workflow_agent.status_code == 201, workflow_agent.text
    workflow_agent_id = workflow_agent.json()["id"]

    async with get_session_factory()() as db:
        server = McpServer(
            workspace_id=workspace_id,
            name="Runtime Server",
            transport="streamable_http",
            url=f"{MODEL_BASE_URL}/mcp",
            tools=[
                {
                    "name": "lookup_release",
                    "description": "Look up a release record.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"topic": {"type": "string"}},
                        "required": ["topic"],
                    },
                }
            ],
            status="active",
            created_by_user_id=admin_user_id,
        )
        await mcp_repository.save_mcp_server(db, server)
        source = await tool_repository.save_tool_source(
            db,
            ToolSource(
                workspace_id=workspace_id,
                mcp_server_id=server.id,
                kind="mcp",
                name=server.name,
                created_by_user_id=admin_user_id,
            ),
        )
        await reconcile_mcp_discovery(db, server, source, server.tools)
        tool = (await tool_repository.list_tools_by_source(
            db,
            workspace_id,
            source.id,
        ))[0]
        assert tool.current_version_id is not None
        await tool_repository.save_application_tool_binding(
            db,
            ApplicationToolBinding(
                workspace_id=workspace_id,
                application_id=agent_id,
                tool_id=tool.id,
                tool_version_id=tool.current_version_id,
                bound_by_user_id=admin_user_id,
            ),
        )
        await db.commit()
        mcp_server_id = server.id

    return {
        "model_id": model_id,
        "reranker_id": reranker_id,
        "knowledge_base_id": knowledge_base_id,
        "rerank_kb_id": rerank_kb_id,
        "agent_id": agent_id,
        "workflow_agent_id": workflow_agent_id,
        "admin_user_id": admin_user_id,
        "mcp_server_id": mcp_server_id,
    }


async def get_admin_actor() -> Any:
    async with get_session_factory()() as db:
        actor = await user_repository.get_active_user_by_username(db, "admin")
        assert actor is not None
        return actor


async def prepare_console_run(
    workspace_id: str,
    agent_id: str,
    goal: str,
) -> tuple[AgentRun, Any]:
    actor = await get_admin_actor()
    async with get_session_factory()() as db:
        run, model = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            agent_id,
            goal,
            actor,
            "admin",
        )
        await db.commit()
        run = await agent_repository.refresh_agent_run(db, run)
        return run, model


def make_conversation_run(
    workspace_id: str,
    agent_id: str,
    user_id: str,
    *,
    conversation_id: str,
    goal: str,
    result: str,
    status: str = "succeeded",
    created_at: Any = None,
    context_summary: str = "",
    index: int = 0,
) -> AgentRun:
    return AgentRun(
        workspace_id=workspace_id,
        agent_id=agent_id,
        requested_by_user_id=user_id,
        execution_user_id=user_id,
        access_source="console",
        consumer_id=user_id,
        conversation_id=conversation_id,
        goal=goal,
        result=result,
        status=status,
        trace_id=f"trace-{index}",
        context_summary=context_summary,
        created_at=created_at or utc_now(),
    )


async def assert_memory_db_paths(
    workspace_id: str,
    agent_id: str,
) -> None:
    actor = await get_admin_actor()
    user_id = actor.id
    conversation_id = "memory-conversation"

    async def save_runs(runs: list[AgentRun]) -> None:
        async with get_session_factory()() as db:
            for run in runs:
                await agent_repository.create_agent_run(db, run)
            await db.commit()

    base_time = utc_now() - timedelta(minutes=30)
    async def spaced(index: int) -> Any:
        return base_time + timedelta(minutes=index)

    # 1) over-budget history with <= RECENT_MEMORY_RUNS runs -> fallback fit (250)
    history = [
        make_conversation_run(
            workspace_id,
            agent_id,
            user_id,
            conversation_id=conversation_id,
            goal="q" * 4000,
            result="a" * 4000,
            created_at=await spaced(index),
            index=index,
        )
        for index in range(3)
    ]
    await save_runs(history)

    current = make_conversation_run(
        workspace_id,
        agent_id,
        user_id,
        conversation_id=conversation_id,
        goal="current question",
        result="",
        status="queued",
        created_at=await spaced(10),
        index=10,
    )
    async with get_session_factory()() as db:
        await agent_repository.create_agent_run(db, current)
        await db.commit()

    class CompactionStub:
        profile = {"max_input_tokens": 32768}

        async def ainvoke(self, _messages):
            raise AssertionError("compaction should not run")

    async with get_session_factory()() as db:
        registered_model = SimpleNamespace(meta={"context_window_tokens": 32768})
        prepared = await agent_memory.prepare_conversation_memory(
            db,
            current,
            registered_model,
            CompactionStub(),
            [{"role": "system", "content": "base"}],
            [],
        )
    # fallback keeps the most recent pair within budget without compaction
    assert 1 <= len(prepared.messages) <= 4
    assert all(
        message["role"] in {"user", "assistant"} for message in prepared.messages
    )

    # 2) fits within budget (242) -> messages mirror the history
    short_history = [
        make_conversation_run(
            workspace_id,
            agent_id,
            user_id,
            conversation_id="memory-conversation-2",
            goal="short q",
            result="short a",
            created_at=await spaced(index),
            index=index,
        )
        for index in range(2)
    ]
    await save_runs(short_history)
    current_short = make_conversation_run(
        workspace_id,
        agent_id,
        user_id,
        conversation_id="memory-conversation-2",
        goal="current",
        result="",
        status="queued",
        created_at=await spaced(10),
        index=11,
    )
    async with get_session_factory()() as db:
        await agent_repository.create_agent_run(db, current_short)
        await db.commit()
    async with get_session_factory()() as db:
        registered_model = SimpleNamespace(meta={"context_window_tokens": 32768})
        prepared = await agent_memory.prepare_conversation_memory(
            db,
            current_short,
            registered_model,
            CompactionStub(),
            [{"role": "system", "content": "base"}],
            [],
        )
    assert len(prepared.messages) == 4
    assert all(
        message["role"] in {"user", "assistant"} for message in prepared.messages
    )

    # 3) budget <= 0 (235)
    async with get_session_factory()() as db:
        registered_model = SimpleNamespace(meta={"context_window_tokens": 32768})
        prepared = await agent_memory.prepare_conversation_memory(
            db,
            current_short,
            registered_model,
            CompactionStub(),
            [{"role": "system", "content": "x" * 60000}],
            [],
        )
    assert prepared.messages == []

    # 4) compaction success with > RECENT_MEMORY_RUNS history (298-299, 313-314,
    #    325-327): six recent runs are kept, older ones are summarized.
    big_history = [
        make_conversation_run(
            workspace_id,
            agent_id,
            user_id,
            conversation_id="memory-conversation-3",
            goal=f"g{index} " * 600,
            result=f"r{index} " * 600,
            created_at=await spaced(index),
            index=index,
        )
        for index in range(8)
    ]
    await save_runs(big_history)
    current_big = make_conversation_run(
        workspace_id,
        agent_id,
        user_id,
        conversation_id="memory-conversation-3",
        goal="current",
        result="",
        status="queued",
        created_at=await spaced(10),
        index=12,
    )
    async with get_session_factory()() as db:
        await agent_repository.create_agent_run(db, current_big)
        await db.commit()

    class SummarizingStub:
        profile = {"max_input_tokens": 32768}

        async def ainvoke(self, _messages):
            return AIMessage(
                content="Durable summary of the old turns.",
                usage_metadata={
                    "input_tokens": 60,
                    "output_tokens": 10,
                    "total_tokens": 70,
                },
            )

    async with get_session_factory()() as db:
        registered_model = SimpleNamespace(meta={"context_window_tokens": 32768})
        prepared = await agent_memory.prepare_conversation_memory(
            db,
            current_big,
            registered_model,
            SummarizingStub(),
            [{"role": "system", "content": "base"}],
            [],
        )
        await db.commit()
    assert prepared.model_usage["compaction"]["input_tokens"] == 60
    assert any(
        "Durable summary" in message["content"] for message in prepared.messages
    )
    async with get_session_factory()() as db:
        anchor = await agent_repository.get_agent_run_by_id(db, big_history[1].id)
    assert anchor is not None
    assert anchor.context_summary == "Durable summary of the old turns."

    # 5) compaction provider failure -> fallback with empty usage (298-299, 302)
    #    and 6) summary save failure (313-314): need enough history after the
    #    anchored summary for the summarizer to be invoked again.
    extra_history = [
        make_conversation_run(
            workspace_id,
            agent_id,
            user_id,
            conversation_id="memory-conversation-3",
            goal="x" * 6000,
            result="y" * 6000,
            created_at=await spaced(index),
            index=index,
        )
        for index in (8, 9)
    ]
    await save_runs(extra_history)

    async with get_session_factory()() as db:
        registered_model = SimpleNamespace(meta={"context_window_tokens": 32768})

        class FailingStub:
            profile = {"max_input_tokens": 32768}

            async def ainvoke(self, _messages):
                raise RuntimeError("provider exploded")

        prepared = await agent_memory.prepare_conversation_memory(
            db,
            current_big,
            registered_model,
            FailingStub(),
            [{"role": "system", "content": "base"}],
            [],
        )
    assert prepared.model_usage["reported_model_calls"] == 0

    # 6) summary save failure -> rollback + fallback (313-314)
    async with get_session_factory()() as db:
        registered_model = SimpleNamespace(meta={"context_window_tokens": 32768})

        class GoodStub:
            profile = {"max_input_tokens": 32768}

            async def ainvoke(self, _messages):
                return AIMessage(content="Another summary.")

        original_save = agent_repository.save_conversation_summary
        agent_repository.save_conversation_summary = (
            async_false_save_conversation_summary
        )
        try:
            prepared = await agent_memory.prepare_conversation_memory(
                db,
                current_big,
                registered_model,
                GoodStub(),
                [{"role": "system", "content": "base"}],
                [],
            )
        finally:
            agent_repository.save_conversation_summary = original_save
    assert prepared.model_usage["reported_model_calls"] == 0


async def async_false_save_conversation_summary(_db, _anchor_run, _summary) -> bool:
    return False


async def assert_knowledge_tool_paths(
    workspace_id: str,
    knowledge_base_id: str,
    rerank_kb_id: str,
) -> None:
    from app.application.agent_tools import (
        build_knowledge_search_tool,
        describe_knowledge_sources,
    )
    actor = await get_admin_actor()

    # empty source description (agent_tools.py:73)
    assert describe_knowledge_sources([]) == "No configured workspace knowledge source."
    named = describe_knowledge_sources(
        [
            KnowledgeBase(
                workspace_id=workspace_id,
                name="Docs",
                description="  Description with \n newline ",
            )
        ]
    )
    assert "- Docs: Description with newline" in named
    anonymous = describe_knowledge_sources(
        [KnowledgeBase(workspace_id=workspace_id, name="", description="")]
    )
    assert "- Unnamed knowledge base" in anonymous

    settings = test_settings()
    base = KnowledgeBase(
        id=knowledge_base_id,
        workspace_id=workspace_id,
        name="Runtime Docs",
    )
    rerank_base = KnowledgeBase(
        id=rerank_kb_id,
        workspace_id=workspace_id,
        name="Reranked Docs",
        reranker_model_id="reranker-model",
    )

    def hit_for(knowledge_base_id: str) -> KnowledgeQueryHitResponse:
        return KnowledgeQueryHitResponse(
            chunk_id=f"chunk-{knowledge_base_id}",
            document_id=f"doc-{knowledge_base_id}",
            document_filename="doc.md",
            chunk_index=0,
            content="Release policy content.",
            distance=0.2,
        )

    async def succeed_retrieve(_db, knowledge_base, payload, _settings):
        assert payload.include_references is True
        return knowledge_inspect_result(
            knowledge_base,
            payload,
            [hit_for(knowledge_base.id)],
        )

    async def fail_retrieve(_db, knowledge_base, _payload, _settings):
        raise HTTPException(status_code=503, detail="source unavailable")

    async def empty_retrieve(_db, knowledge_base, payload, _settings):
        return knowledge_inspect_result(knowledge_base, payload)

    original_retrieve = agent_tools.retrieve_knowledge_base
    original_input = agent_tools.KnowledgeSearchInput
    try:
        agent_tools.retrieve_knowledge_base = succeed_retrieve
        tool = build_knowledge_search_tool(
            [base],
            workspace_id,
            actor,
            "admin",
            settings,
        )
        # inner payload validation failure (138-139): the model-parse step is
        # reached when the outer schema proxy accepts anything.
        class PermissiveInput:
            @classmethod
            def model_json_schema(cls) -> dict:
                return {"type": "object", "properties": {}}

            @classmethod
            def model_validate_json(cls, arguments: str):
                raise ValidationError.from_exception_data(
                    cls.__name__,
                    [
                        {
                            "type": "value_error",
                            "loc": ("body",),
                            "input": arguments,
                            "ctx": {"error": ValueError("invalid payload")},
                        }
                    ],
                )

        agent_tools.KnowledgeSearchInput = PermissiveInput
        invalid = await tool.ainvoke({"query": "q"})
        assert invalid.is_error and invalid.summary == "Invalid search parameters."
        agent_tools.KnowledgeSearchInput = original_input

        # Detailed retrieval owns reranking; Agent consumes the applied status.
        rerank_tool = build_knowledge_search_tool(
            [rerank_base],
            workspace_id,
            actor,
            "admin",
            settings,
        )
        found = await rerank_tool.ainvoke({"query": "release", "limit": 2})
        assert not found.is_error
        assert found.output["evidence_status"] == "found"
        assert found.output["retrieval_stats"][0]["reranked"] is True
        assert found.output["retrieval_stats"][0]["rerank_status"] == "applied"
        assert found.evidence_ids == frozenset({f"chunk-{rerank_kb_id}"})

        # Provider fallback is reported by detailed retrieval without a second pass.
        async def fallback_retrieve(_db, knowledge_base, payload, _settings):
            return knowledge_inspect_result(
                knowledge_base,
                payload,
                [hit_for(knowledge_base.id)],
                "fallback",
            )

        agent_tools.retrieve_knowledge_base = fallback_retrieve
        fallback = await rerank_tool.ainvoke({"query": "release", "limit": 2})
        assert not fallback.is_error
        assert fallback.output["retrieval_stats"][0]["reranked"] is False
        assert fallback.output["retrieval_stats"][0]["rerank_status"] == "fallback"
        assert len(fallback.output["hits"]) == 1

        # all sources fail -> unavailable
        agent_tools.retrieve_knowledge_base = fail_retrieve
        unavailable = await tool.ainvoke({"query": "release", "limit": 2})
        assert unavailable.is_error
        assert unavailable.output["evidence_status"] == "unavailable"

        # mixed failure -> partial_failure: one source errors, the
        # healthy one returns no hits, so no evidence is available.
        async def partial_retrieve(_db, knowledge_base, payload, _settings):
            if knowledge_base.id == rerank_kb_id:
                raise HTTPException(status_code=503, detail="source unavailable")
            return knowledge_inspect_result(knowledge_base, payload)

        mixed_tool = build_knowledge_search_tool(
            [base, rerank_base],
            workspace_id,
            actor,
            "admin",
            settings,
        )
        agent_tools.retrieve_knowledge_base = partial_retrieve
        partial = await mixed_tool.ainvoke({"query": "release", "limit": 2})
        assert partial.output["evidence_status"] == "partial_failure"
        assert partial.is_error
        failed_stats = partial.output["retrieval_stats"]
        assert any(entry["status"] == "unavailable" for entry in failed_stats)

        # no hits at all -> not_found
        agent_tools.retrieve_knowledge_base = empty_retrieve
        missing = await tool.ainvoke({"query": "nothing", "limit": 2})
        assert not missing.is_error
        assert missing.output["evidence_status"] == "not_found"
        assert missing.output["hits"] == []

        # selection stops at the requested limit (269, 271)
        async def two_hits_retrieve(_db, knowledge_base, payload, _settings):
            hits = [
                KnowledgeQueryHitResponse(
                    chunk_id=f"chunk-{knowledge_base.id}-0",
                    document_id="d",
                    document_filename="f.md",
                    chunk_index=0,
                    content="first",
                    distance=0.1,
                ),
                KnowledgeQueryHitResponse(
                    chunk_id=f"chunk-{knowledge_base.id}-1",
                    document_id="d",
                    document_filename="f.md",
                    chunk_index=1,
                    content="second",
                    distance=0.2,
                ),
            ]
            return knowledge_inspect_result(knowledge_base, payload, hits)

        agent_tools.retrieve_knowledge_base = two_hits_retrieve
        select_tool = build_knowledge_search_tool(
            [base],
            workspace_id,
            actor,
            "admin",
            settings,
        )
        selected = await select_tool.ainvoke({"query": "release", "limit": 2})
        assert len(selected.output["hits"]) == 2
        assert selected.output["evidence_status"] == "found"
    finally:
        agent_tools.retrieve_knowledge_base = original_retrieve
        agent_tools.KnowledgeSearchInput = original_input

    # no accessible knowledge bases (154): member user without KB access
    async def no_access(_db, _workspace_id, _knowledge_base_ids, _actor, _role):
        return []

    original_accessible = agent_tools.accessible_agent_knowledge_bases
    agent_tools.accessible_agent_knowledge_bases = no_access
    try:
        tool = build_knowledge_search_tool(
            [base],
            workspace_id,
            actor,
            "admin",
            settings,
        )
        denied = await tool.ainvoke({"query": "release", "limit": 2})
        assert denied.is_error and denied.summary == "Knowledge search failed."
    finally:
        agent_tools.accessible_agent_knowledge_bases = original_accessible


async def assert_mcp_tool_paths(
    workspace_id: str,
    mcp_server_id: str,
) -> None:
    from app.application.agent_tools import build_mcp_agent_tool

    settings = test_settings()
    async with get_session_factory()() as db:
        server = await mcp_repository.get_mcp_server_by_id(db, mcp_server_id)
        assert server is not None
        definition = McpTool(
            name="lookup_release",
            description="Look up a release record.",
            input_schema={
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        )
        resolved = ResolvedMcpTool(server=server, definition=definition)
    tool = build_mcp_agent_tool(resolved, settings, "agent-1", "read_only")

    original_call = agent_tools.call_mcp_tool
    original_resolve = agent_tools.resolve_mcp_tools
    original_set = agent_tools.set_agent_tool_idempotency_key
    try:
        async def fake_resolve(
            _db,
            requested_workspace_id,
            references,
            *,
            strict,
            application_id,
        ):
            assert requested_workspace_id == workspace_id
            assert strict is False
            assert application_id == "agent-1"
            return [] if references[0]["server_id"] == "ghost-server" else [resolved]

        agent_tools.resolve_mcp_tools = fake_resolve

        # inner JSON decode failure (361-362) and non-object payload (370):
        # reachable only when the tool's own schema accepts the arguments, so
        # drive the module-level json reference used by the executor.
        real_json = agent_tools.json

        class ProxyJson:
            def __init__(self, mode: str) -> None:
                self.mode = mode

            def loads(self, value):
                if self.mode == "decode-error":
                    raise json.JSONDecodeError("invalid", value, 0)
                return [1, 2]

            def __getattr__(self, name):
                return getattr(real_json, name)

        agent_tools.json = ProxyJson("decode-error")
        result = await tool.ainvoke({"topic": "release"})
        assert result.is_error and "invalid JSON" in result.content
        agent_tools.json = ProxyJson("not-object")
        result = await tool.ainvoke({"topic": "release"})
        assert result.is_error and "must be an object" in result.content
        agent_tools.json = real_json

        # call with idempotency key set (406-411, 413)
        captured: dict[str, Any] = {}

        async def fake_call(
            connection,
            _settings,
            tool_name,
            arguments,
            *,
            idempotency_key=None,
        ):
            captured["tool_name"] = tool_name
            captured["arguments"] = arguments
            captured["idempotency_key"] = idempotency_key
            return json.dumps({"release": "approved"}), False

        agent_tools.call_mcp_tool = fake_call
        agent_tools.set_agent_tool_idempotency_key("idem-1")
        result = await tool.ainvoke({"topic": "release"})
        assert not result.is_error
        assert captured["idempotency_key"] == "idem-1"
        assert result.output == {"release": "approved"}

        # call without idempotency key (413)
        agent_tools.set_agent_tool_idempotency_key(None)
        result = await tool.ainvoke({"topic": "release"})
        assert captured["idempotency_key"] is None
        assert not result.is_error

        # transport failure surfaces an uncertain result for writes (414-415)
        from app.ports.mcp import McpClientError

        async def failing_call(
            connection,
            _settings,
            tool_name,
            arguments,
            *,
            idempotency_key=None,
        ):
            raise McpClientError("transport interrupted")

        agent_tools.call_mcp_tool = failing_call
        write_tool = build_mcp_agent_tool(
            resolved,
            settings,
            "agent-1",
            "approval_required",
        )
        result = await write_tool.ainvoke({"topic": "release"})
        assert result.is_error and result.outcome_uncertain is True
        assert "request failed" in result.summary
        read_tool = build_mcp_agent_tool(resolved, settings, "agent-1", "read_only")
        result = await read_tool.ainvoke({"topic": "release"})
        assert result.is_error and result.outcome_uncertain is False

        # non-JSON output is truncated to string (424-425)
        async def text_call(
            connection,
            _settings,
            tool_name,
            arguments,
            *,
            idempotency_key=None,
        ):
            return "x" * 9000, False

        agent_tools.call_mcp_tool = text_call
        result = await tool.ainvoke({"topic": "release"})
        assert result.output == "x" * 4000

        # tool no longer resolvable (385)
        ghost = ResolvedMcpTool(
            server=SimpleNamespace(
                id="ghost-server",
                workspace_id=workspace_id,
                name="Ghost",
            ),
            definition=definition,
        )
        ghost_tool = build_mcp_agent_tool(ghost, settings, "agent-1", "read_only")
        result = await ghost_tool.ainvoke({"topic": "release"})
        assert result.is_error and "no longer available" in result.content

        # definition changed (394)
        drifted = ResolvedMcpTool(
            server=SimpleNamespace(
                id=mcp_server_id,
                workspace_id=workspace_id,
                name="Runtime Server",
            ),
            definition=McpTool(
                name="lookup_release",
                description="Different description.",
                input_schema={
                    "type": "object",
                    "properties": {"other": {"type": "string"}},
                },
            ),
        )
        drifted_tool = build_mcp_agent_tool(
            drifted,
            settings,
            "agent-1",
            "read_only",
        )
        result = await drifted_tool.ainvoke({"topic": "release"})
        assert result.is_error and "definition changed" in result.content
    finally:
        agent_tools.call_mcp_tool = original_call
        agent_tools.resolve_mcp_tools = original_resolve
        agent_tools.set_agent_tool_idempotency_key = original_set
        agent_tools.set_agent_tool_idempotency_key(None)


async def assert_run_orchestration_paths(
    workspace_id: str,
    agent_id: str,
    workflow_agent_id: str,
    mcp_server_id: str,
    model_id: str,
) -> None:
    actor = await get_admin_actor()
    settings = test_settings()

    async with get_session_factory()() as db:
        run, _model = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            agent_id,
            "List me",
            actor,
            "admin",
        )
        run.knowledge_base_ids = []
        run.knowledge_query_mode = "agentic"
        run.mcp_tools = []
        await agent_repository.save_agent_run(db, run)
        await db.commit()

        # list_agent_runs (175-176)
        listed = await agent_runs.list_agent_runs(
            db,
            workspace_id,
            agent_id,
            actor,
            "admin",
        )
        assert any(item.id == run.id for item in listed)
        # get_agent_run_response (207) and entity (219-222)
        response = await agent_runs.get_agent_run_response(
            db,
            workspace_id,
            agent_id,
            run.id,
            actor,
            "admin",
        )
        assert response.id == run.id
        entity = await agent_runs.get_agent_run_entity(
            db,
            workspace_id,
            agent_id,
            run.id,
            actor,
            "admin",
        )
        assert entity.id == run.id
        # list tool calls for a run
        calls = await agent_runs.list_agent_run_tool_calls(
            db,
            workspace_id,
            agent_id,
            run.id,
            actor,
            "admin",
        )
        assert calls == []

        # 404 when the run does not belong to the agent (230-231)
        other_agent = Agent(
            workspace_id=workspace_id,
            name="Other Agent",
            instructions="",
            model_id=model_id,
            status="active",
            created_by_user_id=actor.id,
        )
        other_agent = await agent_repository.create_agent(db, other_agent)
        await db.commit()
        try:
            await agent_runs.get_agent_run_entity(
                db,
                workspace_id,
                other_agent.id,
                run.id,
                actor,
                "admin",
            )
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("Cross-agent run lookup was allowed.")

        # workflow app type is rejected (176, 220)
        for call in (
            agent_runs.list_agent_runs(
                db,
                workspace_id,
                workflow_agent_id,
                actor,
                "admin",
            ),
            agent_runs.get_agent_run_entity(
                db,
                workspace_id,
                workflow_agent_id,
                "some-run",
                actor,
                "admin",
            ),
        ):
            try:
                await call
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("Workflow run path was accepted.")

        # prepare_agent_run: invalid access source (410)
        try:
            await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "goal",
                actor,
                "admin",
                access_source="carrier-pigeon",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid access source was accepted.")

        # external run without consumer id (414)
        try:
            await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "goal",
                actor,
                "admin",
                access_source="public",
            )
        except ValueError as exc:
            assert "consumer id" in str(exc)
        else:
            raise AssertionError("External run without consumer id was accepted.")

        # disabled agent (420)
        disabled_agent = Agent(
            workspace_id=workspace_id,
            name="Disabled Agent",
            instructions="",
            model_id=model_id,
            status="disabled",
            created_by_user_id=actor.id,
        )
        disabled_agent = await agent_repository.create_agent(db, disabled_agent)
        await db.commit()
        try:
            await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                disabled_agent.id,
                "goal",
                actor,
                "admin",
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Disabled agent accepted a run.")

        # publication branch (424-425) and non-console conversation (433)
        publication = SimpleNamespace(
            model_id=_model.id,
            knowledge_base_ids=[],
            mcp_tools=[],
            instructions="Published instructions.",
            knowledge_query_mode="agentic",
        )
        published_run, _ = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            agent_id,
            "public goal",
            actor,
            "admin",
            access_source="public",
            consumer_id="external-consumer",
            publication=publication,
        )
        assert published_run.instructions == "Published instructions."
        assert published_run.conversation_id
        assert published_run.access_source == "public"

        # console first run creates a conversation (442): a fresh agent has no
        # prior conversation id on record.
        fresh_run, _ = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            other_agent.id,
            "fresh goal",
            actor,
            "admin",
        )
        assert fresh_run.conversation_id
        first_run, _ = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            agent_id,
            "first goal",
            actor,
            "admin",
        )
        assert first_run.conversation_id

        # active run conflict on an explicit conversation (460)
        explicit_run, _ = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            agent_id,
            "explicit goal",
            actor,
            "admin",
            conversation_id="conflict-conversation",
        )
        assert explicit_run.conversation_id == "conflict-conversation"
        try:
            await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "second explicit goal",
                actor,
                "admin",
                conversation_id="conflict-conversation",
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "active run" in exc.detail
        else:
            raise AssertionError("Second active run in a conversation was accepted.")

        # IntegrityError: a concurrent insert raced the active-run check.
        # The first get_active call returns None (race), the insert then hits
        # the partial unique index and the post-rollback check sees the row.
        original_create = agent_repository.create_agent_run
        original_get_active = agent_repository.get_active_agent_run
        active_check_calls = {"count": 0}

        async def racing_active_run(db, agent_id, access_source, consumer_id, conversation_id):
            active_check_calls["count"] += 1
            if active_check_calls["count"] % 2 == 1:
                return None
            return await original_get_active(
                db,
                agent_id,
                access_source,
                consumer_id,
                conversation_id,
            )

        try:
            agent_repository.create_agent_run = raise_integrity_error
            agent_repository.get_active_agent_run = racing_active_run
            try:
                await agent_runs.prepare_agent_run(
                    db,
                    workspace_id,
                    agent_id,
                    "race goal",
                    actor,
                    "admin",
                    conversation_id="conflict-conversation",
                )
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("IntegrityError race was not converted to 409.")

            # IntegrityError without a competing row re-raises (504-505)
            try:
                await agent_runs.prepare_agent_run(
                    db,
                    workspace_id,
                    agent_id,
                    "race goal two",
                    actor,
                    "admin",
                    conversation_id="fresh-conversation",
                )
            except IntegrityError:
                pass
            else:
                raise AssertionError("IntegrityError was swallowed.")
        finally:
            agent_repository.create_agent_run = original_create
            agent_repository.get_active_agent_run = original_get_active

    # approval resolution paths
    await assert_approval_paths(workspace_id, agent_id, mcp_server_id, settings)


async def raise_integrity_error(_db, _entity):
    raise IntegrityError("INSERT INTO agent_run", {}, Exception("duplicate"))


async def assert_approval_paths(
    workspace_id: str,
    agent_id: str,
    mcp_server_id: str,
    settings: Settings,
) -> None:
    actor = await get_admin_actor()
    async with get_session_factory()() as db:
        run, _ = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            agent_id,
            "approve me",
            actor,
            "admin",
        )
        await agent_repository.save_agent_run(db, run)
        await db.commit()

        async def make_call(status: str, call_id: str, approved_by: str | None = None) -> AgentToolCall:
            call = AgentToolCall(
                workspace_id=workspace_id,
                run_id=run.id,
                turn=1,
                call_id=call_id,
                tool_name="mcp_lookup",
                tool_kind="mcp",
                server_name="Runtime Server",
                arguments_hash="hash-" + call_id,
                idempotency_key="idem-" + call_id,
                definition_hash="def-hash",
                policy_mode="approval_required",
                status=status,
                approval_required=True,
                approved_by_user_id=approved_by,
            )
            call = await agent_repository.create_agent_tool_call(db, call)
            current = await agent_repository.get_agent_run_by_id(db, run.id)
            assert current is not None
            current.status = "awaiting_approval"
            await agent_repository.save_agent_run(db, current)
            await db.commit()
            return call

        # approve path (302-330, 345, 355-358)
        original_enqueue = agent_runs.enqueue_prepared_agent_run
        enqueued: list[str] = []

        async def record_enqueue(run_id: str, _settings) -> None:
            enqueued.append(run_id)

        agent_runs.enqueue_prepared_agent_run = record_enqueue
        try:
            call = await make_call("awaiting_approval", "call-approve")
            refreshed = await agent_runs.resolve_agent_run_tool_approval(
                db,
                run,
                "call-approve",
                actor,
                settings,
                approve=True,
            )
            assert refreshed.id == run.id
            assert run.id in enqueued

            # same actor re-approve -> refresh (291-293)
            again = await agent_runs.resolve_agent_run_tool_approval(
                db,
                run,
                "call-approve",
                actor,
                settings,
                approve=True,
            )
            assert again.id == run.id
            assert len(enqueued) == 1

            # reject path (316, 322-324, 328-330, 345, 355-358)
            await make_call("awaiting_approval", "call-reject")
            rejected_run = await agent_runs.resolve_agent_run_tool_approval(
                db,
                run,
                "call-reject",
                actor,
                settings,
                approve=False,
            )
            assert rejected_run.id == run.id
            assert run.id in enqueued

            # call missing (284-286)
            try:
                await agent_runs.resolve_agent_run_tool_approval(
                    db,
                    run,
                    "call-missing",
                    actor,
                    settings,
                    approve=True,
                )
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("Missing call approval was accepted.")

            # terminal call cannot be approved (292-296)
            await make_call("succeeded", "call-done")
            try:
                await agent_runs.resolve_agent_run_tool_approval(
                    db,
                    run,
                    "call-done",
                    actor,
                    settings,
                    approve=True,
                )
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("Terminal call approval was accepted.")

            # uncertain cannot be approved (297-298)
            await make_call("uncertain", "call-uncertain")
            try:
                await agent_runs.resolve_agent_run_tool_approval(
                    db,
                    run,
                    "call-uncertain",
                    actor,
                    settings,
                    approve=True,
                )
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("Uncertain call approval was accepted.")

            # rejected cannot be approved (302-305)
            await make_call("rejected", "call-rejected")
            try:
                await agent_runs.resolve_agent_run_tool_approval(
                    db,
                    run,
                    "call-rejected",
                    actor,
                    settings,
                    approve=True,
                )
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("Rejected call approval was accepted.")

            # approved cannot be rejected (314-315)
            await make_call("approved", "call-already-approved")
            try:
                await agent_runs.resolve_agent_run_tool_approval(
                    db,
                    run,
                    "call-already-approved",
                    actor,
                    settings,
                    approve=False,
                )
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("Approved call rejection was accepted.")

            # reject fails without status change (322-324)
            await make_call("awaiting_approval", "call-stale")
            original_reject = agent_repository.reject_agent_tool_call
            agent_repository.reject_agent_tool_call = async_false_reject
            try:
                await agent_runs.resolve_agent_run_tool_approval(
                    db,
                    run,
                    "call-stale",
                    actor,
                    settings,
                    approve=False,
                )
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("Failed reject was not reported.")
            finally:
                agent_repository.reject_agent_tool_call = original_reject
        finally:
            agent_runs.enqueue_prepared_agent_run = original_enqueue
            await db.rollback()

    # wrapper path (381-383, 391)
    original_enqueue = agent_runs.enqueue_prepared_agent_run

    async def noop_enqueue(_run_id, _settings) -> None:
        return None

    agent_runs.enqueue_prepared_agent_run = noop_enqueue
    try:
        async with get_session_factory()() as db:
            wrapper_run, _ = await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "wrapper goal",
                actor,
                "admin",
            )
            await agent_repository.save_agent_run(db, wrapper_run)
            await db.commit()
            call = AgentToolCall(
                workspace_id=workspace_id,
                run_id=wrapper_run.id,
                turn=1,
                call_id="call-wrapper",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash="hash-wrapper",
                idempotency_key="idem-wrapper",
                status="awaiting_approval",
                approval_required=True,
            )
            call = await agent_repository.create_agent_tool_call(db, call)
            await db.commit()
            response = await agent_runs.resolve_agent_tool_approval(
                db,
                workspace_id,
                agent_id,
                wrapper_run.id,
                "call-wrapper",
                actor,
                "admin",
                settings,
                approve=False,
            )
            assert response.id == wrapper_run.id
            async with get_session_factory()() as verify_db:
                stored = await agent_repository.get_agent_tool_call_by_call_id(
                    verify_db,
                    wrapper_run.id,
                    "call-wrapper",
                )
            assert stored is not None and stored.status == "rejected"
    finally:
        agent_runs.enqueue_prepared_agent_run = original_enqueue


async def async_false_reject(_db, _tool_call_id, _actor_id, _now) -> bool:
    return False


async def assert_stream_paths(
    workspace_id: str,
    agent_id: str,
) -> None:
    actor = await get_admin_actor()

    class SequenceLiveReader:
        def __init__(self, settings, run_id) -> None:
            self.available = True
            self.read_count = 0

        async def read(self, after, block_ms):
            self.read_count += 1
            if self.read_count == 1:
                return [
                    (
                        "1700000000000-0",
                        {
                            "type": "answer_delta",
                            "delta": "streamed answer",
                            "stream_epoch": "worker-1",
                        },
                    )
                ]
            return []

        async def close(self) -> None:
            return None

    original_reader = agent_runs.AgentLiveStreamReader
    try:
        # non-terminal polling path: live events yielded (599-606), then the
        # run becomes terminal and the complete event is drained (585).
        agent_runs.AgentLiveStreamReader = SequenceLiveReader
        async with get_session_factory()() as db:
            run, model = await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "stream goal",
                actor,
                "admin",
            )
            await agent_repository.save_agent_run(db, run)
            await db.commit()
            stream = agent_runs.stream_agent_run(
                db,
                run,
                model,
                actor,
                "admin",
                test_settings(),
            )
            first = await anext(stream)
            assert first["type"] == "run" and first["run"]["id"] == run.id
            live = await anext(stream)
            assert live["type"] == "answer_delta"
            assert live["live_sequence"] == "1700000000000-0"
            # finish the run from the consumer side
            async with get_session_factory()() as finish_db:
                await agent_repository.append_agent_run_event(
                    finish_db,
                    workspace_id,
                    run.id,
                    {"type": "complete", "run": {"id": run.id}},
                )
                current = await agent_repository.get_agent_run_by_id(finish_db, run.id)
                assert current is not None
                current.status = "succeeded"
                current.result = "streamed answer"
                current.finished_at = utc_now()
                await agent_repository.save_agent_run(finish_db, current)
                await finish_db.commit()
            terminal = await anext(stream)
            assert terminal["type"] == "complete"
            with_sequence = await anext(stream, None)
            assert with_sequence is None

        # terminal without a stored terminal event synthesizes one (585)
        class NoLiveReader:
            def __init__(self, settings, run_id) -> None:
                self.available = False

            async def read(self, after, block_ms):
                return []

            async def close(self) -> None:
                return None

        agent_runs.AgentLiveStreamReader = NoLiveReader
        async with get_session_factory()() as db:
            run, model = await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "synthetic goal",
                actor,
                "admin",
            )
            await agent_repository.save_agent_run(db, run)
            current = await agent_repository.get_agent_run_by_id(db, run.id)
            assert current is not None
            current.status = "succeeded"
            current.result = "done"
            current.finished_at = utc_now()
            await agent_repository.save_agent_run(db, current)
            await db.commit()
            replayed = [
                event
                async for event in agent_runs.stream_agent_run(
                    db,
                    run,
                    model,
                    actor,
                    "admin",
                    test_settings(),
                )
            ]
        assert replayed[0]["type"] == "run"
        assert replayed[-1]["type"] == "complete"
        assert replayed[-1]["run"]["result"] == "done"

        # run disappears mid-stream (554)
        async with get_session_factory()() as db:
            run, model = await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "vanishing goal",
                actor,
                "admin",
            )
            await agent_repository.save_agent_run(db, run)
            await db.commit()
            original_get = agent_repository.get_agent_run_by_id

            async def missing_run(_db, _run_id):
                return None

            agent_repository.get_agent_run_by_id = missing_run
            try:
                replayed = [
                    event
                    async for event in agent_runs.stream_agent_run(
                        db,
                        run,
                        model,
                        actor,
                        "admin",
                        test_settings(),
                    )
                ]
            finally:
                agent_repository.get_agent_run_by_id = original_get
        assert len(replayed) == 1 and replayed[0]["type"] == "run"
    finally:
        agent_runs.AgentLiveStreamReader = original_reader


async def assert_create_agent_run_paths(
    workspace_id: str,
    agent_id: str,
    admin_user_id: str,
    holder: SimpleNamespace,
) -> None:
    actor = await get_admin_actor()
    original_retrieve = agent_tools.retrieve_knowledge_base

    async def no_hits_retrieve(_db, knowledge_base, payload, _settings):
        return knowledge_inspect_result(knowledge_base, payload)

    agent_tools.retrieve_knowledge_base = no_hits_retrieve
    try:
        holder.model = RuntimeModelStub([ok_completion("Created answer.")])
        async with get_session_factory()() as db:
            created = await agent_runs.create_agent_run(
                db,
                workspace_id,
                agent_id,
                "create goal",
                actor,
                "admin",
                test_settings(),
            )
            assert created.goal == "create goal"
            assert created.status == "succeeded"

        # file_ids branch (627, 629)
        import app.application.workflow_uploads as workflow_uploads_module

        original_resolve = workflow_uploads_module.resolve_workspace_agent_files
        holder.model = RuntimeModelStub([ok_completion("Attached answer.")])
        async with get_session_factory()() as db:
            async def fake_resolve(
                _db,
                _workspace_id,
                _agent_id,
                _actor,
                _workspace_role,
                file_ids,
                _settings,
            ) -> str:
                return f"attachment:{','.join(file_ids)}"

            workflow_uploads_module.resolve_workspace_agent_files = fake_resolve
            try:
                attached = await agent_runs.create_agent_run(
                    db,
                    workspace_id,
                    agent_id,
                    "attach goal",
                    actor,
                    "admin",
                    test_settings(),
                    file_ids=["file-1"],
                )
            finally:
                workflow_uploads_module.resolve_workspace_agent_files = original_resolve
        assert attached.status == "succeeded"

        # create without eager execution: the response is still produced from
        # the refreshed run (649-650).
        original_enqueue = agent_runs.enqueue_prepared_agent_run

        async def noop_enqueue(_run_id, _settings) -> None:
            return None

        agent_runs.enqueue_prepared_agent_run = noop_enqueue
        try:
            queued = await agent_runs.create_agent_run(
                db,
                workspace_id,
                agent_id,
                "queued goal",
                actor,
                "admin",
                test_settings(),
            )
        finally:
            agent_runs.enqueue_prepared_agent_run = original_enqueue
        assert queued.goal == "queued goal"
        async with get_session_factory()() as verify_db:
            stored = await agent_repository.get_agent_run_by_id(verify_db, queued.id)
        assert stored is not None and stored.goal == "queued goal"
    finally:
        agent_tools.retrieve_knowledge_base = original_retrieve


async def assert_durable_execution_paths(
    workspace_id: str,
    agent_id: str,
    mcp_server_id: str,
    knowledge_base_id: str,
    holder: SimpleNamespace,
) -> None:
    settings = test_settings()

    # -- happy path with required knowledge and MCP tools in scope --
    run, _ = await prepare_console_run(workspace_id, agent_id, "Happy durable run")
    run.mcp_tools = [{"server_id": mcp_server_id, "tool_name": "lookup_release"}]
    async with get_session_factory()() as db:
        await agent_repository.save_agent_run(db, run)
        await db.commit()

    original_retrieve = agent_tools.retrieve_knowledge_base
    query_calls: list[str] = []

    async def fake_retrieve(_db, knowledge_base, payload, _settings):
        query_calls.append(payload.query)
        return knowledge_inspect_result(knowledge_base, payload)

    agent_tools.retrieve_knowledge_base = fake_retrieve
    holder.model = RuntimeModelStub([ok_completion("Happy answer.")])
    try:
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            settings,
            worker_task_id="worker-happy",
        )
    finally:
        agent_tools.retrieve_knowledge_base = original_retrieve
    assert outcome == agent_executor.RUN_FINISHED
    assert query_calls == ["Happy durable run"]
    async with get_session_factory()() as db:
        current = await agent_repository.get_agent_run_by_id(db, run.id)
        events = await agent_repository.list_agent_run_events(db, run.id)
    assert current is not None
    assert current.status == "succeeded"
    assert current.result == "Happy answer."
    assert current.checkpoint_phase == "done"
    assert current.checkpoint.get("final_answer") == "Happy answer."
    assert events[-1].event["type"] == "complete"

    # -- MCP approval cycle --
    mcp_name = "mcp_lookup_release_" + hashlib.sha256(
        f"{mcp_server_id}:lookup_release".encode()
    ).hexdigest()[:8]
    holder.model = RuntimeModelStub(
        [tool_completion(mcp_name, "call-mcp-1", '{"topic": "release"}')]
    )
    run, _ = await prepare_console_run(workspace_id, agent_id, "Approve the MCP call")
    run.mcp_tools = [{"server_id": mcp_server_id, "tool_name": "lookup_release"}]
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        await agent_repository.save_agent_run(db, run)
        await db.commit()
    original_call = agent_tools.call_mcp_tool

    async def fake_mcp_call(
        connection,
        _settings,
        tool_name,
        arguments,
        *,
        idempotency_key=None,
    ):
        return json.dumps({"release": "approved"}), False

    agent_tools.call_mcp_tool = fake_mcp_call
    try:
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            settings,
            worker_task_id="worker-approval",
        )
        assert outcome == agent_executor.RUN_AWAITING_APPROVAL
        async with get_session_factory()() as db:
            current = await agent_repository.get_agent_run_by_id(db, run.id)
            call = await agent_repository.get_agent_tool_call_by_call_id(
                db, run.id, "call-mcp-1"
            )
        assert current is not None and current.status == "awaiting_approval"
        assert call is not None and call.status == "awaiting_approval"

        # approve and requeue (agent_runs path); suppress the eager re-execution
        # so the second durable attempt can be driven explicitly below.
        actor = await get_admin_actor()
        original_enqueue = agent_runs.enqueue_prepared_agent_run

        async def noop_enqueue(_run_id, _settings) -> None:
            return None

        agent_runs.enqueue_prepared_agent_run = noop_enqueue
        try:
            async with get_session_factory()() as db:
                refreshed = await agent_runs.resolve_agent_run_tool_approval(
                    db,
                    current,
                    "call-mcp-1",
                    actor,
                    settings,
                    approve=True,
                )
                assert refreshed.status == "queued"
        finally:
            agent_runs.enqueue_prepared_agent_run = original_enqueue

        # second attempt resumes from the checkpoint and executes the tool
        holder.model = RuntimeModelStub([ok_completion("Approved answer.")])
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            settings,
            worker_task_id="worker-approval-2",
        )
        assert outcome == agent_executor.RUN_FINISHED
        async with get_session_factory()() as db:
            current = await agent_repository.get_agent_run_by_id(db, run.id)
            call = await agent_repository.get_agent_tool_call_by_call_id(
                db, run.id, "call-mcp-1"
            )
        assert current is not None and current.status == "succeeded"
        assert call is not None and call.status == "succeeded"
        assert call.result_summary == "Runtime Server: lookup_release completed."
    finally:
        agent_tools.call_mcp_tool = original_call

    # -- run timeout (781) --
    short_settings = dataclasses.replace(settings, agent_run_timeout_seconds=0.2)
    holder.model = HangingStreamingProvider()
    run, _ = await prepare_console_run(workspace_id, agent_id, "Timeout this run")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        await agent_repository.save_agent_run(db, run)
        await db.commit()
    outcome = await agent_executor.run_durable_agent_run(
        run.id,
        short_settings,
        worker_task_id="worker-timeout",
    )
    assert outcome == agent_executor.RUN_FINISHED
    async with get_session_factory()() as db:
        current = await agent_repository.get_agent_run_by_id(db, run.id)
        log_rows = await db.execute(
            text("SELECT details FROM system_logs WHERE event = 'agent.execution_failed'")
        )
        logs = log_rows.fetchall()
    assert current is not None and current.status == "failed"
    assert current.last_error == "Agent run timed out."
    assert any("agent_run_id" in (row[0] or {}) for row in logs)

    # -- record_system_log failure inside the error path (871-872) --
    original_record = agent_executor.record_system_log
    agent_executor.record_system_log = raise_runtime_error
    try:
        run, _ = await prepare_console_run(workspace_id, agent_id, "Log failure run")
        run.knowledge_base_ids = []
        run.knowledge_query_mode = "agentic"
        async with get_session_factory()() as db:
            await agent_repository.save_agent_run(db, run)
            await db.commit()
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            short_settings,
            worker_task_id="worker-log-failure",
        )
        assert outcome == agent_executor.RUN_FINISHED
    finally:
        agent_executor.record_system_log = original_record
    async with get_session_factory()() as db:
        current = await agent_repository.get_agent_run_by_id(db, run.id)
    assert current is not None and current.status == "failed"

    # -- finalization lease lost (796) --
    original_finalize = agent_repository.finalize_agent_run
    agent_repository.finalize_agent_run = async_false_finalize
    holder.model = RuntimeModelStub([ok_completion("Finalized?")])
    try:
        run, _ = await prepare_console_run(workspace_id, agent_id, "Finalize race")
        run.knowledge_base_ids = []
        run.knowledge_query_mode = "agentic"
        async with get_session_factory()() as db:
            await agent_repository.save_agent_run(db, run)
            await db.commit()
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            settings,
            worker_task_id="worker-finalize",
        )
        assert outcome == agent_executor.RUN_BUSY
        async with get_session_factory()() as db:
            current = await agent_repository.get_agent_run_by_id(db, run.id)
        assert current is not None and current.status == "queued"
    finally:
        agent_repository.finalize_agent_run = original_finalize

    # -- checkpoint save loses the lease (762-763, 760) --
    original_checkpoint = agent_repository.save_agent_run_checkpoint
    agent_repository.save_agent_run_checkpoint = async_false_checkpoint
    holder.model = RuntimeModelStub([ok_completion("Checkpointed?")])
    try:
        run, _ = await prepare_console_run(workspace_id, agent_id, "Checkpoint race")
        run.knowledge_base_ids = []
        run.knowledge_query_mode = "agentic"
        async with get_session_factory()() as db:
            await agent_repository.save_agent_run(db, run)
            await db.commit()
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            settings,
            worker_task_id="worker-checkpoint",
        )
        assert outcome == agent_executor.RUN_BUSY
    finally:
        agent_repository.save_agent_run_checkpoint = original_checkpoint

    # -- compaction failure falls back to an empty memory (711-721) --
    original_prepare_memory = agent_executor.prepare_conversation_memory
    agent_executor.prepare_conversation_memory = raise_runtime_error_async
    holder.model = RuntimeModelStub([ok_completion("No memory answer.")])
    try:
        run, _ = await prepare_console_run(workspace_id, agent_id, "Memory failure")
        run.knowledge_base_ids = []
        run.knowledge_query_mode = "agentic"
        async with get_session_factory()() as db:
            await agent_repository.save_agent_run(db, run)
            await db.commit()
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            settings,
            worker_task_id="worker-memory-failure",
        )
        assert outcome == agent_executor.RUN_FINISHED
        async with get_session_factory()() as db:
            current = await agent_repository.get_agent_run_by_id(db, run.id)
        assert current is not None and current.status == "succeeded"
        assert current.result == "No memory answer."
    finally:
        agent_executor.prepare_conversation_memory = original_prepare_memory

    # -- approval race: call approved before pause -> requeue (824) --
    original_run_agent = agent_executor.run_agent
    race_actor = await get_admin_actor()
    async with get_session_factory()() as db:
        race_run, _ = await agent_runs.prepare_agent_run(
            db,
            workspace_id,
            agent_id,
            "Approval race",
            race_actor,
            "admin",
        )
        race_run.knowledge_base_ids = []
        race_run.knowledge_query_mode = "agentic"
        await agent_repository.save_agent_run(db, race_run)
        await db.commit()
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=race_run.id,
                turn=1,
                call_id="call-race",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash="hash-race",
                idempotency_key="idem-race",
                status="approved",
                approval_required=True,
                approved_by_user_id=race_actor.id,
            ),
        )
        await db.commit()

    async def pause_during_run(*_args, **_kwargs):
        raise AgentExecutionPaused("call-race", "requires approval")

    agent_executor.run_agent = pause_during_run
    try:
        outcome = await agent_executor.run_durable_agent_run(
            race_run.id,
            settings,
            worker_task_id="worker-race",
        )
        assert outcome == agent_executor.RUN_BUSY
    finally:
        agent_executor.run_agent = original_run_agent

    # -- pause fails -> RUN_BUSY (826) --
    original_pause = agent_repository.pause_agent_run
    agent_repository.pause_agent_run = async_false_pause
    try:
        run, _ = await prepare_console_run(workspace_id, agent_id, "Pause failure")
        run.knowledge_base_ids = []
        run.knowledge_query_mode = "agentic"
        async with get_session_factory()() as db:
            await agent_repository.save_agent_run(db, run)
            await db.commit()
        agent_executor.run_agent = pause_during_run
        try:
            outcome = await agent_executor.run_durable_agent_run(
                run.id,
                settings,
                worker_task_id="worker-pause-fail",
            )
            assert outcome == agent_executor.RUN_BUSY
        finally:
            agent_executor.run_agent = original_run_agent
    finally:
        agent_repository.pause_agent_run = original_pause

    # -- lease_lost set before the graph starts (751, 812-815) --
    run, _ = await prepare_console_run(workspace_id, agent_id, "Lost lease run")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        await agent_repository.save_agent_run(db, run)
        await db.commit()
    async with get_session_factory()() as db:
        now = utc_now()
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-lost-lease",
            now,
            now + timedelta(seconds=30),
        )
        await db.commit()
    lease_lost = asyncio.Event()
    lease_lost.set()
    outcome = await agent_executor._execute_claimed_agent_run(
        run.id,
        "worker-lost-lease",
        settings,
        lease_lost,
    )
    assert outcome == agent_executor.RUN_BUSY

    # -- claim failures (981, 984-985) --
    # exhausted run -> failed -> RUN_FINISHED (985)
    run, _ = await prepare_console_run(workspace_id, agent_id, "Exhausted claim")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        current = await agent_repository.get_agent_run_by_id(db, run.id)
        assert current is not None
        current.status = "running"
        current.attempts = current.max_attempts
        current.worker_task_id = "dead-worker"
        current.lease_expires_at = utc_now() - timedelta(seconds=1)
        await agent_repository.save_agent_run(db, current)
        await db.commit()
    outcome = await agent_executor.run_durable_agent_run(
        run.id,
        settings,
        worker_task_id="worker-exhausted",
    )
    assert outcome == agent_executor.RUN_FINISHED
    async with get_session_factory()() as db:
        current = await agent_repository.get_agent_run_by_id(db, run.id)
    assert current is not None and current.status == "failed"

    # live run owned by another worker -> RUN_BUSY (984)
    run, _ = await prepare_console_run(workspace_id, agent_id, "Busy claim")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        now = utc_now()
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-owner",
            now,
            now + timedelta(seconds=60),
        )
        await db.commit()
    outcome = await agent_executor.run_durable_agent_run(
        run.id,
        settings,
        worker_task_id="worker-interloper",
    )
    assert outcome == agent_executor.RUN_BUSY

    # missing run -> AgentRunnerError (888)
    try:
        await agent_executor.run_durable_agent_run(
            "run-does-not-exist",
            settings,
            worker_task_id="worker-missing",
        )
    except AgentRunnerError as exc:
        assert "no longer exists" in str(exc)
    else:
        raise AssertionError("Missing run did not raise.")

    # -- _fail_unhandled_claimed_run: run deleted mid-flight (913) --
    original_execute = agent_executor._execute_claimed_agent_run
    original_get = agent_repository.get_agent_run_by_id
    run, _ = await prepare_console_run(workspace_id, agent_id, "Delete mid-flight")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"

    async def raise_after_delete(_run_id, _worker, _settings, _lease_lost):
        raise RuntimeError("run vanished")

    async def missing_run(_db, _run_id):
        return None

    agent_executor._execute_claimed_agent_run = raise_after_delete
    agent_repository.get_agent_run_by_id = missing_run
    try:
        async with get_session_factory()() as db:
            await agent_repository.save_agent_run(db, run)
            await db.commit()
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            settings,
            worker_task_id="worker-delete",
        )
        assert outcome == agent_executor.RUN_FINISHED
    finally:
        agent_executor._execute_claimed_agent_run = original_execute
        agent_repository.get_agent_run_by_id = original_get

    # -- _fail_unhandled_claimed_run: error event appended (917-918, 929-946) --
    original_execute = agent_executor._execute_claimed_agent_run
    run, _ = await prepare_console_run(workspace_id, agent_id, "Unhandled failure")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"

    async def append_then_raise(_run_id, _worker, _settings, _lease_lost):
        async with get_session_factory()() as db:
            current = await agent_repository.get_agent_run_by_id(db, _run_id)
            assert current is not None
            await agent_repository.append_agent_run_event(
                db,
                current.workspace_id,
                current.id,
                {
                    "type": "process",
                    "event": {
                        "type": "thought",
                        "turn": 1,
                        "tool_name": "",
                        "status": "succeeded",
                        "summary": "agent.analyzing",
                        "call_id": "",
                        "tool_label": "",
                        "tool_kind": "unknown",
                        "server_name": "",
                        "input": {},
                        "output": None,
                        "reasoning": "",
                    },
                },
            )
            await db.commit()
        raise RuntimeError("unhandled boom")

    agent_executor._execute_claimed_agent_run = append_then_raise
    try:
        async with get_session_factory()() as db:
            await agent_repository.save_agent_run(db, run)
            await db.commit()
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            settings,
            worker_task_id="worker-unhandled",
        )
        assert outcome == agent_executor.RUN_FINISHED
        async with get_session_factory()() as db:
            current = await agent_repository.get_agent_run_by_id(db, run.id)
            events = await agent_repository.list_agent_run_events(db, run.id)
        assert current is not None and current.status == "failed"
        assert current.last_error == "Agent execution failed."
        assert events[-1].event["type"] == "error"
    finally:
        agent_executor._execute_claimed_agent_run = original_execute

    # -- _fail_unhandled_claimed_run: finalize fails -> RUN_BUSY (949-950) --
    original_finalize = agent_repository.finalize_agent_run
    agent_repository.finalize_agent_run = async_false_finalize
    original_execute = agent_executor._execute_claimed_agent_run
    run, _ = await prepare_console_run(workspace_id, agent_id, "Unhandled finalize")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"

    async def raise_boom(_run_id, _worker, _settings, _lease_lost):
        raise RuntimeError("boom")

    agent_executor._execute_claimed_agent_run = raise_boom
    try:
        async with get_session_factory()() as db:
            await agent_repository.save_agent_run(db, run)
            await db.commit()
        outcome = await agent_executor.run_durable_agent_run(
            run.id,
            settings,
            worker_task_id="worker-unhandled-2",
        )
        assert outcome == agent_executor.RUN_BUSY
    finally:
        agent_repository.finalize_agent_run = original_finalize
        agent_executor._execute_claimed_agent_run = original_execute

    # -- maintain_agent_run_lease: renewed (583-592) --
    run, _ = await prepare_console_run(workspace_id, agent_id, "Heartbeat renew")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    heartbeat_settings = dataclasses.replace(
        settings,
        agent_executor_heartbeat_seconds=1,
        agent_executor_lease_seconds=90,
    )
    async with get_session_factory()() as db:
        now = utc_now()
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-heartbeat",
            now,
            now + timedelta(seconds=90),
        )
        await db.commit()
    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        agent_executor.maintain_agent_run_lease(
            run.id,
            "worker-heartbeat",
            heartbeat_settings,
            lease_lost,
        )
    )
    await asyncio.sleep(1.4)
    heartbeat.cancel()
    with _suppress(asyncio.CancelledError):
        await heartbeat
    assert not lease_lost.is_set()
    async with get_session_factory()() as db:
        current = await agent_repository.get_agent_run_by_id(db, run.id)
    assert current is not None
    assert current.lease_expires_at is not None
    assert current.lease_expires_at > now.replace(tzinfo=None) + timedelta(seconds=88)

    # -- maintain_agent_run_lease: lease taken over (593-595) --
    run, _ = await prepare_console_run(workspace_id, agent_id, "Heartbeat takeover")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        now = utc_now()
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-heartbeat-1",
            now,
            now + timedelta(seconds=90),
        )
        current = await agent_repository.get_agent_run_by_id(db, run.id)
        assert current is not None
        current.lease_expires_at = now - timedelta(seconds=1)
        await agent_repository.save_agent_run(db, current)
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-heartbeat-2",
            now,
            now + timedelta(seconds=90),
        )
        await db.commit()
    lease_lost = asyncio.Event()
    await agent_executor.maintain_agent_run_lease(
        run.id,
        "worker-heartbeat-1",
        heartbeat_settings,
        lease_lost,
    )
    assert lease_lost.is_set()

    # -- maintain_agent_run_lease: renewal exception (596-598) --
    original_renew = agent_repository.renew_agent_run_lease
    agent_repository.renew_agent_run_lease = raise_runtime_error_async
    try:
        run, _ = await prepare_console_run(workspace_id, agent_id, "Heartbeat error")
        run.knowledge_base_ids = []
        run.knowledge_query_mode = "agentic"
        async with get_session_factory()() as db:
            now = utc_now()
            assert await agent_repository.claim_agent_run(
                db,
                run.id,
                "worker-heartbeat-3",
                now,
                now + timedelta(seconds=90),
            )
            await db.commit()
        lease_lost = asyncio.Event()
        await agent_executor.maintain_agent_run_lease(
            run.id,
            "worker-heartbeat-3",
            heartbeat_settings,
            lease_lost,
        )
        assert lease_lost.is_set()
    finally:
        agent_repository.renew_agent_run_lease = original_renew

    # -- _load_execution_scope: run not executable (455) --
    queued_run, _ = await prepare_console_run(workspace_id, agent_id, "Scope queued")
    queued_run.knowledge_base_ids = []
    queued_run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        await agent_repository.save_agent_run(db, queued_run)
        await db.commit()
    try:
        await agent_executor._load_execution_scope(queued_run.id)
    except AgentRunnerError as exc:
        assert "not executable" in str(exc)
    else:
        raise AssertionError("Queued run was executed.")

    # -- _load_execution_scope: user unavailable (458) --
    run, _ = await prepare_console_run(workspace_id, agent_id, "Scope actor gone")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        await agent_repository.save_agent_run(db, run)
        await db.commit()
    async with get_session_factory()() as db:
        now = utc_now()
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-scope",
            now,
            now + timedelta(seconds=30),
        )
        await db.commit()
    original_get_user = agent_executor.user_repository.get_user_by_id

    async def missing_user(_db, _user_id):
        return None

    agent_executor.user_repository.get_user_by_id = missing_user
    try:
        await agent_executor._load_execution_scope(run.id)
    except AgentRunnerError as exc:
        assert "user is unavailable" in str(exc)
    else:
        raise AssertionError("Run with a missing actor was executed.")
    finally:
        agent_executor.user_repository.get_user_by_id = original_get_user

    # -- _pause_agent_run_for_tool: no matching call -> approval_required event (559-561) --
    run, _ = await prepare_console_run(workspace_id, agent_id, "Pause without call")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        now = utc_now()
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-pause",
            now,
            now + timedelta(seconds=30),
        )
        await db.commit()
    paused, requeued = await agent_executor._pause_agent_run_for_tool(
        run.id,
        "worker-pause",
        "call-not-created",
        "Tool call requires user approval.",
    )
    assert paused and not requeued
    async with get_session_factory()() as db:
        events = await agent_repository.list_agent_run_events(db, run.id)
        current = await agent_repository.get_agent_run_by_id(db, run.id)
    assert current is not None and current.status == "awaiting_approval"
    assert any(
        event.event.get("type") == "approval_required" for event in events
    )

    # -- _append_event loses the run lease (530) --
    run, _ = await prepare_console_run(workspace_id, agent_id, "Append lease lost")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        now = utc_now()
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-append-1",
            now,
            now + timedelta(seconds=30),
        )
        current = await agent_repository.get_agent_run_by_id(db, run.id)
        assert current is not None
        current.lease_expires_at = now - timedelta(seconds=1)
        await agent_repository.save_agent_run(db, current)
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-append-2",
            now,
            now + timedelta(seconds=30),
        )
        await db.commit()
    try:
        await agent_executor._append_event(
            run,
            {"type": "process", "event": {"status": "running"}},
            worker_task_id="worker-append-1",
        )
    except AgentToolBusy:
        pass
    else:
        raise AssertionError("Lost lease did not raise AgentToolBusy.")

    # -- DurableToolLedger unit paths --
    await assert_ledger_db_paths(workspace_id, agent_id, mcp_server_id, settings)

    # -- list_recoverable_agent_run_ids (1017-1023) --
    run, _ = await prepare_console_run(workspace_id, agent_id, "Recoverable run")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        now = utc_now()
        assert await agent_repository.claim_agent_run(
            db,
            run.id,
            "worker-recover",
            now - timedelta(minutes=10),
            now - timedelta(minutes=9),
        )
        await db.commit()
    recoverable = await agent_executor.list_recoverable_agent_run_ids(settings)
    assert run.id in recoverable


async def assert_ledger_db_paths(
    workspace_id: str,
    agent_id: str,
    mcp_server_id: str,
    settings: Settings,
) -> None:
    actor = await get_admin_actor()
    metadata = {
        "kind": "mcp",
        "policy_mode": "approval_required",
        "server_id": mcp_server_id,
        "source_tool_name": "lookup_release",
        "server_name": "Runtime Server",
        "definition_hash": "def-v2",
    }
    read_only_metadata = {
        **metadata,
        "kind": "knowledge",
        "policy_mode": "read_only",
    }
    disabled_metadata = {
        **metadata,
        "kind": "knowledge",
        "policy_mode": "disabled",
    }

    async def new_ledger(run, lease_lost=None):
        return agent_executor.DurableToolLedger(
            run,
            "worker-ledger",
            settings,
            lease_lost or asyncio.Event(),
        )

    # lease lost (238)
    run, _ = await prepare_console_run(workspace_id, agent_id, "Ledger lease lost")
    run.knowledge_base_ids = []
    run.knowledge_query_mode = "agentic"
    lost = asyncio.Event()
    lost.set()
    ledger = await new_ledger(run, lost)
    try:
        await ledger.before(1, pending_call("call-x"), metadata, {"topic": "x"})
    except AgentToolBusy:
        pass
    else:
        raise AssertionError("Lease loss was not surfaced by the ledger.")

    # create + claim + after + replay (returns None first, then stored result)
    ledger = await new_ledger(run)
    first = await ledger.before(
        1, pending_call("call-1"), read_only_metadata, {"topic": "x"}
    )
    assert first is None
    async with get_session_factory()() as db:
        stored = await agent_repository.get_agent_tool_call(
            db, run.id, 1, "call-1"
        )
    assert stored is not None and stored.status == "running"
    assert stored.worker_task_id == "worker-ledger"
    await ledger.after(
        1,
        pending_call("call-1"),
        read_only_metadata,
        {"topic": "x"},
        AgentToolResult(content="durable result", summary="durable summary"),
    )
    replayed = await ledger.before(
        1, pending_call("call-1"), read_only_metadata, {"topic": "x"}
    )
    assert replayed is not None and replayed.content == "durable result"

    # identity change (317)
    async with get_session_factory()() as db:
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=run.id,
                turn=2,
                call_id="call-identity",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash="different-hash",
                idempotency_key="idem-identity",
                definition_hash="def-v2",
                status="approved",
                approval_required=False,
            ),
        )
        await db.commit()
    try:
        await ledger.before(
            2, pending_call("call-identity"), read_only_metadata, {"topic": "y"}
        )
    except AgentToolUncertain as exc:
        assert "identity changed" in exc.reason
    else:
        raise AssertionError("Identity change was not detected.")

    # definition changed -> blocked result (322-337, 147)
    async with get_session_factory()() as db:
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=run.id,
                turn=3,
                call_id="call-def",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash=agent_executor._arguments_hash({"topic": "z"}),
                idempotency_key="idem-def",
                definition_hash="stale-def",
                status="approved",
                approval_required=False,
            ),
        )
        await db.commit()
    blocked = await ledger.before(
        3, pending_call("call-def"), read_only_metadata, {"topic": "z"}
    )
    assert blocked is not None and blocked.is_error
    assert "definition changed" in blocked.content

    # disabled policy (338-354)
    blocked = await ledger.before(
        4, pending_call("call-disabled"), disabled_metadata, {"topic": "z"}
    )
    assert blocked is not None and blocked.is_error
    assert "disabled by workspace policy" in blocked.content

    # escalation: previously approved call now requires approval (360-373)
    async with get_session_factory()() as db:
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=run.id,
                turn=5,
                call_id="call-escalate",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash=agent_executor._arguments_hash({"topic": "e"}),
                idempotency_key="idem-escalate",
                definition_hash="def-v2",
                status="approved",
                approval_required=False,
            ),
        )
        await db.commit()
    try:
        await ledger.before(
            5, pending_call("call-escalate"), metadata, {"topic": "e"}
        )
    except AgentExecutionPaused as exc:
        assert "approval" in exc.reason
    else:
        raise AssertionError("Approval escalation was not enforced.")
    async with get_session_factory()() as db:
        escalated = await agent_repository.get_agent_tool_call(
            db, run.id, 5, "call-escalate"
        )
    assert escalated is not None and escalated.status == "awaiting_approval"
    assert escalated.policy_mode == "approval_required"

    # uncertain status (382)
    async with get_session_factory()() as db:
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=run.id,
                turn=6,
                call_id="call-uncertain",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash=agent_executor._arguments_hash({"topic": "u"}),
                idempotency_key="idem-uncertain",
                definition_hash="def-v2",
                status="uncertain",
                approval_required=False,
                last_error="maybe happened",
            ),
        )
        await db.commit()
    try:
        await ledger.before(
            6, pending_call("call-uncertain"), read_only_metadata, {"topic": "u"}
        )
    except AgentToolUncertain as exc:
        assert "maybe happened" in exc.reason
    else:
        raise AssertionError("Uncertain call was not surfaced.")

    # running status owned elsewhere (387)
    async with get_session_factory()() as db:
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=run.id,
                turn=7,
                call_id="call-busy",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash=agent_executor._arguments_hash({"topic": "b"}),
                idempotency_key="idem-busy",
                definition_hash="def-v2",
                status="running",
                approval_required=False,
                worker_task_id="other-worker",
            ),
        )
        await db.commit()
    try:
        await ledger.before(
            7, pending_call("call-busy"), read_only_metadata, {"topic": "b"}
        )
    except AgentToolBusy as exc:
        assert "another worker" in exc.reason
    else:
        raise AssertionError("Busy call was claimed by the wrong worker.")

    # succeeded status replays the stored result (374-375)
    async with get_session_factory()() as db:
        await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=run.id,
                turn=8,
                call_id="call-done",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash=agent_executor._arguments_hash({"topic": "d"}),
                idempotency_key="idem-done",
                definition_hash="def-v2",
                status="succeeded",
                approval_required=False,
                result_content="already done",
                result_summary="done summary",
                result_output={"ok": True},
                result_is_error=False,
            ),
        )
        await db.commit()
    replayed = await ledger.before(
        8, pending_call("call-done"), read_only_metadata, {"topic": "d"}
    )
    assert replayed is not None and replayed.content == "already done"

    # after() with a missing ledger entry (418)
    try:
        await ledger.after(
            9,
            pending_call("call-missing-after"),
            metadata,
            {"topic": "a"},
            AgentToolResult(content="x", summary="s"),
        )
    except AgentRunnerError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("Missing ledger entry was not detected.")

    # after() success path (419-438)
    claim_run, _ = await prepare_console_run(workspace_id, agent_id, "Ledger after")
    claim_run.knowledge_base_ids = []
    claim_run.knowledge_query_mode = "agentic"
    async with get_session_factory()() as db:
        now = utc_now()
        call = await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=claim_run.id,
                turn=1,
                call_id="call-after",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash="hash-after",
                idempotency_key="idem-after",
                definition_hash="def-v2",
                status="approved",
                approval_required=False,
            ),
        )
        assert await agent_repository.claim_agent_tool_call(
            db,
            call.id,
            "worker-after",
            now,
            now + timedelta(seconds=30),
        )
        await db.commit()
    after_ledger = agent_executor.DurableToolLedger(
        claim_run,
        "worker-after",
        settings,
        asyncio.Event(),
    )
    await after_ledger.after(
        1,
        pending_call("call-after"),
        read_only_metadata,
        {"topic": "x"},
        AgentToolResult(
            content="result text",
            summary="result summary",
            output={"value": 1},
            evidence_ids=frozenset({"chunk-a"}),
        ),
    )
    async with get_session_factory()() as db:
        stored = await agent_repository.get_agent_tool_call(
            db, claim_run.id, 1, "call-after"
        )
    assert stored is not None and stored.status == "succeeded"
    assert stored.result_content == "result text"
    assert stored.result_evidence_ids == ["chunk-a"]

    # after() save fails -> AgentToolUncertain (440)
    original_save = agent_repository.save_agent_tool_call_result
    agent_repository.save_agent_tool_call_result = async_false_save_result
    try:
        async with get_session_factory()() as db:
            now = utc_now()
            call = await agent_repository.create_agent_tool_call(
                db,
                AgentToolCall(
                    workspace_id=workspace_id,
                    run_id=claim_run.id,
                    turn=2,
                    call_id="call-after-fail",
                    tool_name="mcp_lookup",
                    tool_kind="mcp",
                    arguments_hash="hash-after-fail",
                    idempotency_key="idem-after-fail",
                    definition_hash="def-v2",
                    status="approved",
                    approval_required=False,
                ),
            )
            assert await agent_repository.claim_agent_tool_call(
                db,
                call.id,
                "worker-after",
                now,
                now + timedelta(seconds=30),
            )
            await db.commit()
        try:
            await after_ledger.after(
                2,
                pending_call("call-after-fail"),
                read_only_metadata,
                {"topic": "x"},
                AgentToolResult(content="c", summary="s"),
            )
        except AgentToolUncertain as exc:
            assert "durably recorded" in exc.reason
        else:
            raise AssertionError("Unrecorded tool result was not detected.")
    finally:
        agent_repository.save_agent_tool_call_result = original_save

    # after() with outcome_uncertain (444-447)
    async with get_session_factory()() as db:
        now = utc_now()
        call = await agent_repository.create_agent_tool_call(
            db,
            AgentToolCall(
                workspace_id=workspace_id,
                run_id=claim_run.id,
                turn=3,
                call_id="call-after-uncertain",
                tool_name="mcp_lookup",
                tool_kind="mcp",
                arguments_hash="hash-after-uncertain",
                idempotency_key="idem-after-uncertain",
                definition_hash="def-v2",
                status="approved",
                approval_required=False,
            ),
        )
        assert await agent_repository.claim_agent_tool_call(
            db,
            call.id,
            "worker-after",
            now,
            now + timedelta(seconds=30),
        )
        await db.commit()
    try:
        await after_ledger.after(
            3,
            pending_call("call-after-uncertain"),
            read_only_metadata,
            {"topic": "x"},
            AgentToolResult(
                content="c",
                summary="s",
                outcome_uncertain=True,
            ),
        )
    except AgentToolUncertain as exc:
        assert "confirm its state" in exc.reason
    else:
        raise AssertionError("Uncertain outcome was not surfaced.")
    async with get_session_factory()() as db:
        stored = await agent_repository.get_agent_tool_call(
            db, claim_run.id, 3, "call-after-uncertain"
        )
    assert stored is not None and stored.status == "uncertain"


def pending_call(call_id: str, name: str = "mcp_lookup") -> dict[str, str]:
    return {"id": call_id, "name": name, "arguments": "{}"}


def raise_runtime_error(*_args, **_kwargs):
    raise RuntimeError("synthetic failure")


async def raise_runtime_error_async(*_args, **_kwargs):
    raise RuntimeError("synthetic failure")


async def async_false_finalize(*_args, **_kwargs) -> bool:
    return False


async def async_false_checkpoint(*_args, **_kwargs) -> bool:
    return False


async def async_false_pause(*_args, **_kwargs) -> bool:
    return False


async def async_false_save_result(*_args, **_kwargs) -> bool:
    return False


def _suppress(*exceptions):
    class Suppressor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return exc_type is not None and issubclass(exc_type, exceptions)

    return Suppressor()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    assert_usage_normalization()
    assert_agent_tool_construction()
    assert_callback_safety()
    assert_graph_error_branches()
    assert_executor_checkpoint_paths()
    assert_ledger_pure_helpers()
    assert_live_stream_degradation()
    assert_event_replay_cursor_error()
    assert_memory_pure_functions()

    holder = SimpleNamespace(model=None)
    original_build_chat_model = agent_executor.build_chat_model

    def patched_build_chat_model(_settings, _model):
        assert holder.model is not None, "model stub was not installed"
        return holder.model

    agent_executor.build_chat_model = patched_build_chat_model
    try:
        with test_client() as client, agent_model_server() as model_base_url:
            admin_token, workspace_id = activate_admin(client)
            resources = asyncio.run(
                db_setup(client, admin_token, workspace_id, model_base_url)
            )
            asyncio.run(
                assert_memory_db_paths(workspace_id, resources["agent_id"])
            )
            asyncio.run(
                assert_knowledge_tool_paths(
                    workspace_id,
                    resources["knowledge_base_id"],
                    resources["rerank_kb_id"],
                )
            )
            asyncio.run(
                assert_mcp_tool_paths(workspace_id, resources["mcp_server_id"])
            )
            asyncio.run(
                assert_run_orchestration_paths(
                    workspace_id,
                    resources["agent_id"],
                    resources["workflow_agent_id"],
                    resources["mcp_server_id"],
                    resources["model_id"],
                )
            )
            asyncio.run(
                assert_stream_paths(workspace_id, resources["agent_id"])
            )
            asyncio.run(
                assert_create_agent_run_paths(
                    workspace_id,
                    resources["agent_id"],
                    resources["admin_user_id"],
                    holder,
                )
            )
            asyncio.run(
                assert_durable_execution_paths(
                    workspace_id,
                    resources["agent_id"],
                    resources["mcp_server_id"],
                    resources["knowledge_base_id"],
                    holder,
                )
            )
    finally:
        agent_executor.build_chat_model = original_build_chat_model

    print("OK: agent runtime coverage suite passed.")


if __name__ == "__main__":
    main()
