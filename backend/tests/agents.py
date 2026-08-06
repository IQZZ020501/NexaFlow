import asyncio
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from types import SimpleNamespace

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from mcp.types import Tool as McpTool
from sqlalchemy import select

from app.application import agent_runs, agent_tools
from app.application import agents as agent_application
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import user as user_repository
from app.application.agent_memory import (
    MAX_MEMORY_TOTAL_CHARS,
    format_conversation_memory,
)
from app.capabilities.llm.runtime import ModelCompletion, ModelToolCall
from app.capabilities.mcp import client as mcp_client_module
from app.capabilities.mcp.client import (
    MAX_MCP_TOOL_PAGES,
    McpClientError,
    discover_mcp_tools,
    normalize_mcp_url,
)
from app.schemas.knowledge import KnowledgeQueryHitResponse
from app.infrastructure.session import get_session_factory
from app.infrastructure.system_log import SystemLog
from app.shareddomain.agents.runtime import (
    AgentRunnerError,
    AgentToolResult,
    create_agent_tool,
    run_agent,
    safe_event_value,
)
from app.shareddomain.agents.runtime import graph as agent_graph_module
from app.shareddomain.agents.runtime.graph import MAX_REASONING_CHARS
from app.shareddomain.tools import services as mcp_services
from tests.support import (
    activate_admin,
    activate_user,
    auth_headers,
    create_active_user,
    settings as test_settings,
    test_client,
)

MEMBER_PASSWORD = "AgentMember@12345."


class AgentModelHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        AgentModelHandler.calls.append(body)

        tool_names = {
            tool["function"]["name"]
            for tool in body.get("tools", [])
            if tool.get("type") == "function"
        }
        mcp_tool_name = next(
            (name for name in tool_names if name.startswith("mcp_")),
            None,
        )
        if "search_knowledge" in tool_names and not any(
            item.get("role") == "tool" for item in body.get("messages", [])
        ):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-search",
                        "type": "function",
                        "function": {
                            "name": "search_knowledge",
                            "arguments": json.dumps({"query": "release process"}),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        elif mcp_tool_name and not any(
            item.get("role") == "tool" for item in body.get("messages", [])
        ):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-mcp",
                        "type": "function",
                        "function": {
                            "name": mcp_tool_name,
                            "arguments": json.dumps({"topic": "release"}),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "Completed."}
            finish_reason = "stop"

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            delta = {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": [
                    {
                        "index": index,
                        **tool_call,
                    }
                    for index, tool_call in enumerate(message.get("tool_calls", []))
                ],
            }
            chunks = [
                {
                    "id": "agent-test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "agent-test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": finish_reason,
                        }
                    ],
                },
            ]
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return

        payload = {
            "id": "agent-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
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
    AgentModelHandler.calls = []
    server = HTTPServer(("127.0.0.1", 0), AgentModelHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def model_payload(api_base: str, name: str = "Agent Model") -> dict:
    return {
        "name": name,
        "provider": "model_deepseek_provider",
        "provider_type": "deepseek",
        "model_type": "LLM",
        "model_name": "deepseek-chat",
        "credential": {"api_base": api_base, "api_key": "sk-agent-test-1234"},
    }


def agents_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/agents{suffix}"


def knowledge_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge-bases{suffix}"


def mcp_url(workspace_id: str, suffix: str = "") -> str:
    return f"/api/v1/workspaces/{workspace_id}/mcp-servers{suffix}"


def create_workspace_user(client, token: str, workspace_id: str) -> tuple[str, str]:
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/members/users",
        headers=auth_headers(token),
        json={
            "username": "agent-member",
            "email": "agent-member@example.com",
            "name": "Agent Member",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]["id"], response.json()["initial_password"]


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
    def __init__(self, completions: list[ModelCompletion]) -> None:
        self.completions = completions
        self.requests: list[list[BaseMessage]] = []

    def bind_tools(self, *_args, **_kwargs):
        return self

    def next_completion(self, messages: list[BaseMessage]) -> ModelCompletion:
        self.requests.append(list(messages))
        return self.completions.pop(0)

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        return completion_message(self.next_completion(messages))


class StreamingProvider(SequenceProvider):
    def __init__(
        self,
        completions: list[ModelCompletion],
        reasoning: list[list[str]],
    ) -> None:
        super().__init__(completions)
        self.reasoning = reasoning

    async def astream(self, messages: list[BaseMessage]):
        completion = self.next_completion(messages)
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


class RepeatedToolProvider:
    def __init__(self, tool_name: str, calls_before_answer: int) -> None:
        self.tool_name = tool_name
        self.calls_before_answer = calls_before_answer
        self.turn = 0

    def bind_tools(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, _messages: list[BaseMessage]) -> AIMessage:
        self.turn += 1
        if self.turn <= self.calls_before_answer:
            return completion_message(
                ModelCompletion(
                    content="",
                    tool_calls=(
                        ModelToolCall(
                            f"call-{self.turn}",
                            self.tool_name,
                            '{"query": "release"}',
                        ),
                    ),
                    finish_reason="tool_calls",
                )
            )
        return completion_message(
            ModelCompletion(
                content="Done.",
                tool_calls=(),
                finish_reason="stop",
            )
        )


class HangingStreamingProvider:
    def bind_tools(self, *_args, **_kwargs):
        return self

    async def astream(self, _messages: list[BaseMessage]):
        await asyncio.Event().wait()
        yield AIMessageChunk(content="")


async def assert_hanging_model_stream_times_out() -> None:
    async def emit(_event: dict) -> None:
        return None

    original_timeout = getattr(
        agent_graph_module,
        "MODEL_RESPONSE_TIMEOUT_SECONDS",
        None,
    )
    agent_graph_module.MODEL_RESPONSE_TIMEOUT_SECONDS = 0.01
    try:
        try:
            await asyncio.wait_for(
                run_agent(
                    HangingStreamingProvider(),  # type: ignore[arg-type]
                    [{"role": "user", "content": "Run it"}],
                    [],
                    on_event=emit,
                ),
                timeout=0.1,
            )
        except AgentRunnerError as exc:
            assert str(exc) == "Agent model response timed out."
        except TimeoutError as exc:
            raise AssertionError("Agent model stream did not time out.") from exc
        else:
            raise AssertionError("Hanging agent model stream completed.")
    finally:
        if original_timeout is None:
            del agent_graph_module.MODEL_RESPONSE_TIMEOUT_SECONDS
        else:
            agent_graph_module.MODEL_RESPONSE_TIMEOUT_SECONDS = original_timeout


async def assert_truncated_tool_call_is_not_executed() -> None:
    executions = 0

    async def execute(_arguments: str) -> AgentToolResult:
        nonlocal executions
        executions += 1
        return AgentToolResult(content="ok", summary="ok")

    provider = SequenceProvider(
        [
            ModelCompletion(
                content="",
                tool_calls=(ModelToolCall("call-1", "test_tool", '{"value":'),),
                finish_reason="length",
            ),
            ModelCompletion(content="Stopped safely.", tool_calls=(), finish_reason="stop"),
        ]
    )
    result = await run_agent(
        provider,  # type: ignore[arg-type]
        [{"role": "user", "content": "Run it"}],
        [
            create_agent_tool(
                name="test_tool",
                description="Test tool",
                parameters={"type": "object"},
                execute=execute,
            )
        ],
    )
    assert result.content == "Stopped safely."
    assert result.events[0]["status"] == "failed"
    assert executions == 0


async def assert_invalid_tool_arguments_are_not_executed() -> None:
    executions = 0

    async def execute(_arguments: str) -> AgentToolResult:
        nonlocal executions
        executions += 1
        return AgentToolResult(content="ok", summary="ok")

    result = await run_agent(
        SequenceProvider(
            [
                ModelCompletion(
                    content="",
                    tool_calls=(ModelToolCall("call-1", "test_tool", "not-json"),),
                    finish_reason="tool_calls",
                ),
                ModelCompletion(content="Recovered.", tool_calls=(), finish_reason="stop"),
            ]
        ),  # type: ignore[arg-type]
        [{"role": "user", "content": "Run it"}],
        [
            create_agent_tool(
                name="test_tool",
                description="Test tool",
                parameters={"type": "object"},
                execute=execute,
            )
        ],
    )
    assert result.content == "Recovered."
    assert result.events[0]["status"] == "failed"
    assert executions == 0


async def assert_tool_error_returns_to_model() -> None:
    async def execute(_arguments: str) -> AgentToolResult:
        raise RuntimeError("private tool failure")

    provider = SequenceProvider(
        [
            ModelCompletion(
                content="",
                tool_calls=(ModelToolCall("call-1", "test_tool", "{}"),),
                finish_reason="tool_calls",
            ),
            ModelCompletion(content="Recovered.", tool_calls=(), finish_reason="stop"),
        ]
    )
    result = await run_agent(
        provider,  # type: ignore[arg-type]
        [{"role": "user", "content": "Run it"}],
        [
            create_agent_tool(
                name="test_tool",
                description="Test tool",
                parameters={"type": "object"},
                execute=execute,
            )
        ],
    )
    assert result.content == "Recovered."
    assert result.events[0]["status"] == "failed"



async def assert_streaming_run_emits_process_and_answer() -> None:
    emitted: list[dict] = []

    async def emit(event: dict) -> None:
        emitted.append(event)

    async def execute(_arguments: str) -> AgentToolResult:
        return AgentToolResult(content="tool result", summary="Tool completed.")

    provider = StreamingProvider(
        [
            ModelCompletion(
                content="",
                tool_calls=(ModelToolCall("call-1", "test_tool", "{}"),),
                finish_reason="tool_calls",
            ),
            ModelCompletion(content="Streamed answer.", tool_calls=(), finish_reason="stop"),
        ],
        [[], ["Inspect ", "x" * MAX_REASONING_CHARS]],
    )
    result = await run_agent(
        provider,  # type: ignore[arg-type]
        [{"role": "user", "content": "Run it"}],
        [
            create_agent_tool(
                name="test_tool",
                description="Test tool",
                parameters={"type": "object"},
                execute=execute,
            )
        ],
        on_event=emit,
    )
    assert result.content == "Streamed answer."
    assert [event["type"] for event in emitted] == [
        "process",
        "process",
        "process",
        "process",
        "process",
        "reasoning_delta",
        "reasoning_delta",
        "process",
        "answer_delta",
    ]
    assert emitted[0]["event"]["type"] == "thought"
    assert emitted[2]["event"]["type"] == "tool"
    assert emitted[5] == {
        "type": "reasoning_delta",
        "turn": 2,
        "delta": "Inspect ",
    }
    assert len(emitted[6]["delta"]) == MAX_REASONING_CHARS - len("Inspect ")
    assert len(emitted[7]["event"]["reasoning"]) == MAX_REASONING_CHARS
    assert emitted[-1]["delta"] == "Streamed answer."


async def assert_parallel_policy_is_enforced() -> None:
    active = 0
    max_parallel = 0

    async def execute(_arguments: str) -> AgentToolResult:
        nonlocal active, max_parallel
        active += 1
        max_parallel = max(max_parallel, active)
        await asyncio.sleep(0.01)
        active -= 1
        return AgentToolResult(content="ok", summary="ok")

    calls = tuple(
        ModelToolCall(f"call-{index}", "test_tool", '{"value": 1}')
        for index in range(2)
    )
    provider = SequenceProvider(
        [
            ModelCompletion(content="", tool_calls=calls, finish_reason="tool_calls"),
            ModelCompletion(content="Done.", tool_calls=(), finish_reason="stop"),
        ]
    )
    tool = create_agent_tool(
        name="test_tool",
        description="Test tool",
        parameters={"type": "object"},
        execute=execute,
        parallel_safe=True,
    )
    result = await run_agent(
        provider,  # type: ignore[arg-type]
        [{"role": "user", "content": "Run it"}],
        [tool],
    )
    assert max_parallel == 2
    assert [event["call_id"] for event in result.events] == ["call-0", "call-1"]

    max_parallel = 0
    provider = SequenceProvider(
        [
            ModelCompletion(content="", tool_calls=calls, finish_reason="tool_calls"),
            ModelCompletion(content="Done.", tool_calls=(), finish_reason="stop"),
        ]
    )
    serial_tool = create_agent_tool(
        name="test_tool",
        description="Test tool",
        parameters={"type": "object"},
        execute=execute,
    )
    await run_agent(
        provider,  # type: ignore[arg-type]
        [{"role": "user", "content": "Run it"}],
        [serial_tool],
    )
    assert max_parallel == 1


async def assert_runtime_budgets_are_enforced() -> None:
    retrievals = 0

    async def retrieve(_arguments: str) -> AgentToolResult:
        nonlocal retrievals
        retrievals += 1
        return AgentToolResult(
            content="hit",
            summary="hit",
            output={"retrieval_stats": [{"submitted": 1}]},
            evidence_ids=frozenset({f"chunk-{retrievals}"}),
        )

    knowledge_tool = create_agent_tool(
        name="search_knowledge",
        description="Search",
        parameters={"type": "object"},
        execute=retrieve,
        kind="knowledge",
        parallel_safe=True,
    )
    result = await run_agent(
        RepeatedToolProvider("search_knowledge", 5),  # type: ignore[arg-type]
        [{"role": "user", "content": "Run it"}],
        [knowledge_tool],
    )
    assert retrievals == 5
    assert len(result.events) == 5
    assert all(event["status"] == "succeeded" for event in result.events)

    executions = 0

    async def execute(_arguments: str) -> AgentToolResult:
        nonlocal executions
        executions += 1
        return AgentToolResult(content="ok", summary="ok")

    ordinary_tool = create_agent_tool(
        name="test_tool",
        description="Test",
        parameters={"type": "object"},
        execute=execute,
    )
    try:
        await run_agent(
            SequenceProvider(
                [
                    ModelCompletion(
                        content="",
                        tool_calls=tuple(
                            ModelToolCall(f"call-{index}", "test_tool", "{}")
                            for index in range(13)
                        ),
                        finish_reason="tool_calls",
                    )
                ]
            ),  # type: ignore[arg-type]
            [{"role": "user", "content": "Run it"}],
            [ordinary_tool],
        )
    except AgentRunnerError as exc:
        assert str(exc) == "Agent tool call limit reached."
    else:
        raise AssertionError("Agent tool call budget was not enforced.")
    assert executions == 0

    try:
        await run_agent(
            RepeatedToolProvider("test_tool", 8),  # type: ignore[arg-type]
            [{"role": "user", "content": "Run it"}],
            [ordinary_tool],
        )
    except AgentRunnerError as exc:
        assert str(exc) == "Agent turn limit reached."
    else:
        raise AssertionError("Agent turn budget was not enforced.")


async def assert_retrieval_progress_uses_evidence_ids() -> None:
    async def retrieve(arguments: str) -> AgentToolResult:
        query = json.loads(arguments)["query"]
        return AgentToolResult(
            content="hit",
            summary="hit",
            output={"retrieval_stats": [{"submitted": 1}]},
            evidence_ids=frozenset({f"chunk-{query}"}),
        )

    knowledge_tool = create_agent_tool(
        name="search_knowledge",
        description="Search",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        execute=retrieve,
        kind="knowledge",
        parallel_safe=True,
    )

    def completion(call_id: str, query: str) -> ModelCompletion:
        return ModelCompletion(
            content="",
            tool_calls=(
                ModelToolCall(call_id, "search_knowledge", json.dumps({"query": query})),
            ),
            finish_reason="tool_calls",
        )

    distinct_provider = SequenceProvider(
        [
            completion("call-1", "one"),
            completion("call-2", "two"),
            completion("call-3", "three"),
            ModelCompletion(content="Done.", tool_calls=(), finish_reason="stop"),
        ]
    )
    await run_agent(
        distinct_provider,  # type: ignore[arg-type]
        [{"role": "user", "content": "Run it"}],
        [knowledge_tool],
    )
    assert not any(
        "No new evidence found" in message.text
        for message in distinct_provider.requests[-1]
    )

    repeated_provider = SequenceProvider(
        [
            completion("call-1", "same"),
            completion("call-2", "same"),
            completion("call-3", "same"),
            ModelCompletion(content="Done.", tool_calls=(), finish_reason="stop"),
        ]
    )
    await run_agent(
        repeated_provider,  # type: ignore[arg-type]
        [{"role": "user", "content": "Run it"}],
        [knowledge_tool],
    )
    assert any(
        "No new evidence found" in message.text
        for message in repeated_provider.requests[-1]
    )


async def assert_structured_tool_and_event_safety() -> None:
    executions = 0

    async def execute(_arguments: str) -> AgentToolResult:
        nonlocal executions
        executions += 1
        return AgentToolResult(content="ok", summary="ok")

    definition = McpTool(
        name="test_tool",
        description="Test tool",
        inputSchema={
            "type": "object",
            "$defs": {
                "payload": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "child": {"$ref": "#/$defs/payload"},
                    },
                    "required": ["value"],
                    "additionalProperties": False,
                }
            },
            "properties": {"payload": {"$ref": "#/$defs/payload"}},
            "required": ["payload"],
        },
    )
    tool = create_agent_tool(
        name=definition.name,
        description=definition.description or "",
        parameters=definition.input_schema,
        execute=execute,
    )
    assert isinstance(tool, StructuredTool)
    assert tool.args_schema == definition.input_schema
    model_schema = convert_to_openai_tool(tool)["function"]["parameters"]
    assert "$defs" not in json.dumps(model_schema)
    assert "$ref" not in json.dumps(model_schema)
    invalid = await tool.ainvoke(
        {"payload": {"value": "ok", "child": {}}}
    )
    assert invalid.is_error is True
    assert executions == 0
    valid = await tool.ainvoke(
        {"payload": {"value": "ok", "child": {"value": "nested"}}}
    )
    assert valid.is_error is False
    assert executions == 1

    reserved_names = create_agent_tool(
        name="reserved_names",
        description="Test reserved property names",
        parameters={
            "type": "object",
            "properties": {
                "$id": {"type": "string"},
                "definitions": {"type": "string"},
            },
            "required": ["$id", "definitions"],
            "additionalProperties": False,
        },
        execute=execute,
    )
    assert set(reserved_names.args_schema["properties"]) == {"$id", "definitions"}
    reserved_result = await reserved_names.ainvoke(
        {"$id": "customer-1", "definitions": "active"}
    )
    assert reserved_result.is_error is False
    safe = safe_event_value(
        {
            "authorization": "Bearer secret",
            "nested": {"api_key": "secret", "value": "x" * 3000},
        }
    )
    assert safe["authorization"] == "[REDACTED]"
    assert safe["nested"]["api_key"] == "[REDACTED]"
    assert len(safe["nested"]["value"]) == 2000


def assert_conversation_memory_is_bounded() -> None:
    def run(index: int, status: str = "succeeded") -> SimpleNamespace:
        return SimpleNamespace(
            status=status,
            goal=f"question-{index}-" + "q" * 1000,
            result=f"answer-{index}-" + "a" * 1000,
        )

    memory = format_conversation_memory(
        [
            run(12),
            run(11),
            run(10, "failed"),
            *[run(index) for index in range(9, -1, -1)],
        ]
    )
    assert "question-12" in memory
    assert "question-11" in memory
    assert "question-10" not in memory  # failed runs are excluded
    assert "question-0" in memory  # 11 succeeded runs fit the 60000-char budget
    assert len(memory) <= MAX_MEMORY_TOTAL_CHARS

    # the total budget still caps: a 40-run history exceeds 60000 chars,
    # so the oldest runs are dropped while the newest stay.
    overflow = format_conversation_memory(
        [run(index) for index in range(39, -1, -1)]
    )
    assert "question-39" in overflow
    assert "question-0" not in overflow
    assert len(overflow) <= MAX_MEMORY_TOTAL_CHARS


async def assert_cancelled_run_marked_failed(run_id: str) -> None:
    cancelled_run = None
    for _ in range(50):
        async with get_session_factory()() as db:
            cancelled_run = await agent_repository.get_agent_run_by_id(db, run_id)
            if (
                cancelled_run is not None
                and cancelled_run.status == "failed"
                and cancelled_run.last_error == "Agent run cancelled."
            ):
                return
        await asyncio.sleep(0.1)
    raise AssertionError(
        f"cancelled run was not marked failed (status={cancelled_run.status if cancelled_run else None})"
    )


async def assert_stream_disconnect_marks_run_failed(
    workspace_id: str,
    agent_id: str,
) -> None:
    started = asyncio.Event()
    hang = asyncio.Event()

    async def hanging_run_agent(*_args, **_kwargs):
        started.set()
        await hang.wait()

    original_run_agent = agent_runs.run_agent
    agent_runs.run_agent = hanging_run_agent
    try:
        async with get_session_factory()() as db:
            actor = await user_repository.get_active_user_by_username(db, "admin")
            assert actor is not None
            run, model = await agent_runs.prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "Cancel me",
                actor,
                "admin",
            )
            stream = agent_runs.stream_agent_run(
                db,
                run,
                model,
                actor,
                "admin",
                test_settings(),
            )
            first_event = await anext(stream)
            assert first_event["type"] == "run"
            assert first_event["run"]["id"] == run.id
            await asyncio.wait_for(started.wait(), timeout=1)
            await stream.aclose()
        await assert_cancelled_run_marked_failed(run.id)
    finally:
        agent_runs.run_agent = original_run_agent
        hang.set()


async def get_agent_failure_log(trace_id: str) -> SystemLog | None:
    async with get_session_factory()() as db:
        return await db.scalar(
            select(SystemLog).where(
                SystemLog.event == "agent.execution_failed",
                SystemLog.details["trace_id"].as_string() == trace_id,
            )
        )


def assert_mcp_url_validation() -> None:
    assert normalize_mcp_url("https://tools.example.com/mcp/") == (
        "https://tools.example.com/mcp"
    )
    for invalid_url in (
        "file:///tmp/mcp.sock",
        "https://tools.example.com/mcp?token=secret",
        "https://tools.example.com:invalid/mcp",
    ):
        try:
            normalize_mcp_url(invalid_url)
        except McpClientError:
            continue
        raise AssertionError(f"Invalid MCP URL was accepted: {invalid_url}")


async def assert_mcp_discovery_rejects_untrusted_metadata() -> None:
    original_client = mcp_client_module.mcp_client

    class FakeClient:
        def __init__(self, schema: dict, next_cursor: str | None) -> None:
            self.schema = schema
            self.next_cursor = next_cursor
            self.calls = 0

        async def list_tools(self, **_kwargs):
            self.calls += 1
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="unsafe_tool",
                        description=None,
                        input_schema=self.schema,
                    )
                ],
                next_cursor=self.next_cursor,
            )

    async def run_discovery(client: FakeClient) -> None:
        @asynccontextmanager
        async def fake_client(*_args, **_kwargs):
            yield client

        mcp_client_module.mcp_client = fake_client  # type: ignore[assignment]
        try:
            await discover_mcp_tools("https://tools.example.com", None, False, 1)
        except McpClientError:
            return
        raise AssertionError("Invalid MCP tool metadata was accepted.")

    try:
        await run_discovery(FakeClient({"type": "string"}, None))
        paginated_client = FakeClient({"type": "object"}, "same-cursor")
        await run_discovery(paginated_client)
        assert paginated_client.calls == MAX_MCP_TOOL_PAGES
    finally:
        mcp_client_module.mcp_client = original_client


def main() -> None:
    asyncio.run(assert_hanging_model_stream_times_out())
    asyncio.run(assert_truncated_tool_call_is_not_executed())
    asyncio.run(assert_invalid_tool_arguments_are_not_executed())
    asyncio.run(assert_tool_error_returns_to_model())
    asyncio.run(assert_mcp_discovery_rejects_untrusted_metadata())
    asyncio.run(assert_streaming_run_emits_process_and_answer())
    asyncio.run(assert_parallel_policy_is_enforced())
    asyncio.run(assert_runtime_budgets_are_enforced())
    asyncio.run(assert_retrieval_progress_uses_evidence_ids())
    asyncio.run(assert_structured_tool_and_event_safety())
    assert_conversation_memory_is_bounded()
    assert_mcp_url_validation()

    original_query = agent_tools.query_knowledge_base
    original_discover = mcp_services.discover_mcp_tools
    original_call_mcp_tool = agent_tools.call_mcp_tool
    original_run_agent = agent_runs.run_agent
    query_calls: list[tuple[str, str]] = []
    mcp_calls: list[tuple[str, str, dict]] = []

    async def fake_query_knowledge_base(
        _db,
        knowledge_base,
        payload,
        _settings,
    ) -> list[KnowledgeQueryHitResponse]:
        query_calls.append((knowledge_base.id, payload.query))
        return [
            KnowledgeQueryHitResponse(
                chunk_id="chunk-agent-source",
                document_id="document-agent-source",
                document_filename="release.md",
                chunk_index=0,
                content="Deployments require an approved pull request.",
                distance=0.1,
            )
        ]

    async def fake_discover_mcp_tools(
        _url,
        bearer_token,
        _allow_private_networks,
        _timeout_seconds,
    ) -> list[dict]:
        assert bearer_token == "mcp-secret-token"
        return [
            {
                "name": "lookup_release",
                "description": "Look up a release record.",
                "input_schema": {
                    "type": "object",
                    "properties": {"topic": {"type": "string"}},
                    "required": ["topic"],
                },
            }
        ]

    async def fake_call_mcp_tool(
        url,
        bearer_token,
        tool_name,
        arguments,
        _allow_private_networks,
        _timeout_seconds,
    ) -> tuple[str, bool]:
        assert bearer_token == "mcp-secret-token"
        mcp_calls.append((url, tool_name, arguments))
        return json.dumps({"release": "approved"}), False

    agent_tools.query_knowledge_base = fake_query_knowledge_base
    mcp_services.discover_mcp_tools = fake_discover_mcp_tools
    agent_tools.call_mcp_tool = fake_call_mcp_tool
    try:
        with test_client() as client, agent_model_server() as model_base_url:
            admin_token, workspace_id = activate_admin(client)
            member_id, temporary_password = create_workspace_user(
                client,
                admin_token,
                workspace_id,
            )
            member_token = activate_user(
                client,
                "agent-member",
                temporary_password,
                MEMBER_PASSWORD,
            )

            model = client.post(
                f"/api/v1/workspaces/{workspace_id}/models",
                headers=auth_headers(admin_token),
                json=model_payload(model_base_url),
            )
            assert model.status_code == 201, model.text
            model_id = model.json()["id"]

            knowledge_base = client.post(
                knowledge_url(workspace_id),
                headers=auth_headers(admin_token),
                json={"name": "Release Docs", "description": "Deployment rules"},
            )
            assert knowledge_base.status_code == 201, knowledge_base.text
            knowledge_base_id = knowledge_base.json()["id"]

            created = client.post(
                agents_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Release Planner",
                    "description": "Plans release work",
                    "instructions": "Use workspace evidence before answering.",
                    "model_id": model_id,
                    "knowledge_base_ids": [knowledge_base_id],
                },
            )
            assert created.status_code == 201, created.text
            agent = created.json()
            agent_id = agent["id"]
            assert agent["can_edit"] is True
            assert agent["knowledge_base_ids"] == [knowledge_base_id]

            async def fail_agent_run(*_args, **_kwargs):
                raise RuntimeError("synthetic runtime failure")

            agent_runs.run_agent = fail_agent_run
            try:
                failed_run_response = client.post(
                    agents_url(workspace_id, f"/{agent_id}/runs"),
                    headers=auth_headers(admin_token),
                    json={"goal": "Verify failure observability"},
                )
            finally:
                agent_runs.run_agent = original_run_agent
            assert failed_run_response.status_code == 201, failed_run_response.text
            failed_run = failed_run_response.json()
            assert failed_run["status"] == "failed"
            assert failed_run["last_error"] == "Agent execution failed."
            failure_log = asyncio.run(get_agent_failure_log(failed_run["trace_id"]))
            assert failure_log is not None
            assert failure_log.details["agent_run_id"] == failed_run["id"]
            assert failure_log.details["agent_id"] == agent_id
            assert failure_log.details["exception_type"] == "RuntimeError"
            assert "synthetic runtime failure" in (failure_log.stack_trace or "")

            asyncio.run(
                assert_stream_disconnect_marks_run_failed(
                    workspace_id,
                    agent_id,
                )
            )

            duplicate = client.post(
                agents_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Release Planner",
                    "instructions": "Duplicate",
                    "model_id": model_id,
                },
            )
            assert duplicate.status_code == 409, duplicate.text

            member_list = client.get(
                agents_url(workspace_id),
                headers=auth_headers(member_token),
            )
            assert member_list.status_code == 200, member_list.text
            assert member_list.json()[0]["can_edit"] is False
            assert member_list.json()[0]["knowledge_base_ids"] == []


            member_update = client.patch(
                agents_url(workspace_id, f"/{agent_id}"),
                headers=auth_headers(member_token),
                json={"name": "Changed"},
            )
            assert member_update.status_code == 403, member_update.text

            member_question = client.post(
                agents_url(workspace_id, f"/{agent_id}/runs"),
                headers=auth_headers(member_token),
                json={"goal": "Prepare the release"},
            )
            assert member_question.status_code == 201, member_question.text
            member_run = member_question.json()
            assert member_run["status"] == "succeeded"
            assert member_run["plan"] == []
            plan_calls = [
                call
                for call in AgentModelHandler.calls
                if any(
                    item.get("role") == "system"
                    and "You plan goals for an AI agent" in item.get("content", "")
                    for item in call.get("messages", [])
                )
            ]
            assert plan_calls == []
            assert "citations" not in member_run
            assert query_calls == []

            grant = client.put(
                knowledge_url(workspace_id, f"/{knowledge_base_id}/permissions/{member_id}"),
                headers=auth_headers(admin_token),
                json={"permission": "view"},
            )
            assert grant.status_code == 200, grant.text

            permitted_question = client.post(
                agents_url(workspace_id, f"/{agent_id}/runs"),
                headers=auth_headers(member_token),
                json={"goal": "Prepare the release with evidence"},
            )
            assert permitted_question.status_code == 201, permitted_question.text
            executed = permitted_question.json()
            assert executed["status"] == "succeeded"
            assert executed["result"] == "Completed."
            assert executed["events"][0]["tool_name"] == "search_knowledge"
            assert "citations" not in executed
            assert query_calls == [(knowledge_base_id, "release process")]
            knowledge_event = executed["events"][0]
            assert knowledge_event["call_id"] == "call-search"
            assert knowledge_event["tool_label"] == "知识库检索"
            assert knowledge_event["tool_kind"] == "knowledge"
            assert knowledge_event["input"] == {"query": "release process"}
            assert "source_id" not in knowledge_event["output"]["hits"][0]
            assert knowledge_event["output"]["hits"][0]["document"] == "release.md"

            member_mcp_create = client.post(
                mcp_url(workspace_id),
                headers=auth_headers(member_token),
                json={
                    "name": "Release MCP",
                    "url": "http://127.0.0.1:9999/mcp",
                },
            )
            assert member_mcp_create.status_code == 403, member_mcp_create.text

            mcp_server = client.post(
                mcp_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Release MCP",
                    "url": "http://127.0.0.1:9999/mcp",
                    "bearer_token": "mcp-secret-token",
                },
            )
            assert mcp_server.status_code == 201, mcp_server.text
            mcp_server_data = mcp_server.json()
            assert mcp_server_data["has_bearer_token"] is True
            assert "bearer_token" not in mcp_server_data

            mcp_agent = client.post(
                agents_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Release Tool Agent",
                    "model_id": model_id,
                    "mcp_tools": [
                        {
                            "server_id": mcp_server_data["id"],
                            "tool_name": "lookup_release",
                        }
                    ],
                },
            )
            assert mcp_agent.status_code == 201, mcp_agent.text
            mcp_agent_data = mcp_agent.json()
            assert mcp_agent_data["mcp_tools"][0]["tool_name"] == "lookup_release"

            mcp_question = client.post(
                agents_url(workspace_id, f"/{mcp_agent_data['id']}/runs"),
                headers=auth_headers(admin_token),
                json={"goal": "Check the release"},
            )
            assert mcp_question.status_code == 201, mcp_question.text
            mcp_run = mcp_question.json()
            assert mcp_run["status"] == "succeeded"
            assert mcp_run["events"][0]["status"] == "succeeded"
            mcp_event = mcp_run["events"][0]
            assert mcp_event["call_id"] == "call-mcp"
            assert mcp_event["tool_label"] == "lookup_release"
            assert mcp_event["tool_kind"] == "mcp"
            assert mcp_event["server_name"] == "Release MCP"
            assert mcp_event["input"] == {"topic": "release"}
            assert mcp_event["output"] == {"release": "approved"}
            assert mcp_calls == [
                (
                    "http://127.0.0.1:9999/mcp",
                    "lookup_release",
                    {"topic": "release"},
                )
            ]

            member_agent = client.post(
                agents_url(workspace_id),
                headers=auth_headers(member_token),
                json={
                    "name": "Member Agent",
                    "instructions": "Use permitted workspace knowledge.",
                    "model_id": model_id,
                    "knowledge_base_ids": [knowledge_base_id],
                },
            )
            assert member_agent.status_code == 201, member_agent.text
            revoked = client.delete(
                knowledge_url(
                    workspace_id,
                    f"/{knowledge_base_id}/permissions/{member_id}",
                ),
                headers=auth_headers(admin_token),
            )
            assert revoked.status_code == 204, revoked.text
            member_agent_update = client.patch(
                agents_url(workspace_id, f"/{member_agent.json()['id']}"),
                headers=auth_headers(member_token),
                json={
                    "description": "Updated without knowledge access",
                    "instructions": "",
                },
            )
            assert member_agent_update.status_code == 200, member_agent_update.text
            assert member_agent_update.json()["knowledge_base_ids"] == []
            assert member_agent_update.json()["instructions"]

            other_admin_id, other_token = create_active_user(
                client,
                admin_token,
                "other-admin",
            )
            created_workspace = client.post(
                "/api/v1/workspaces",
                headers=auth_headers(admin_token),
                json={
                    "name": "Other Workspace",
                    "admin_user_id": other_admin_id,
                },
            )
            assert created_workspace.status_code == 201, created_workspace.text
            other_workspace_id = created_workspace.json()["workspace"]["id"]
            other_model = client.post(
                f"/api/v1/workspaces/{other_workspace_id}/models",
                headers=auth_headers(other_token),
                json=model_payload(model_base_url, "Other Agent Model"),
            )
            assert other_model.status_code == 201, other_model.text

            cross_workspace_model = client.post(
                agents_url(workspace_id),
                headers=auth_headers(admin_token),
                json={
                    "name": "Cross Workspace Agent",
                    "instructions": "Invalid",
                    "model_id": other_model.json()["id"],
                },
            )
            assert cross_workspace_model.status_code == 422, cross_workspace_model.text

            disabled_model = client.patch(
                f"/api/v1/workspaces/{workspace_id}/models/{model_id}",
                headers=auth_headers(admin_token),
                json={"status": "disabled"},
            )
            assert disabled_model.status_code == 200, disabled_model.text

            disabled = client.patch(
                agents_url(workspace_id, f"/{agent_id}"),
                headers=auth_headers(admin_token),
                json={"model_id": model_id, "status": "disabled"},
            )
            assert disabled.status_code == 200, disabled.text
            assert disabled.json()["status"] == "disabled"

            deleted = client.delete(
                agents_url(workspace_id, f"/{agent_id}"),
                headers=auth_headers(admin_token),
            )
            assert deleted.status_code == 204, deleted.text

            audit_logs = client.get(
                "/api/v1/admin/audit-logs",
                headers=auth_headers(admin_token),
            )
            actions = [item["action"] for item in audit_logs.json()]
            assert "agent.create" in actions
            assert "agent.delete" in actions
    finally:
        agent_tools.query_knowledge_base = original_query
        mcp_services.discover_mcp_tools = original_discover
        agent_tools.call_mcp_tool = original_call_mcp_tool
        agent_runs.run_agent = original_run_agent


if __name__ == "__main__":
    main()
