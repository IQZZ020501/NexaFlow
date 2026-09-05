"""Workflow node execution and public access coverage suite.

Run from ``backend/`` with ``uv run python -m tests.workflow_node_coverage``.
Covers the baseline-missing lines of ``app/application/workflow_executor.py``,
``app/application/workflow_nodes.py``, ``app/application/workflow_uploads.py``,
``app/application/workflow_access.py`` and
``app/api/v1/endpoints/workflow_access.py``.
"""

import asyncio
import io
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401

from app.schemas.workflow import WorkflowNode
from app.shareddomain.agents.runtime.tools import AgentToolResult
from app.shareddomain.workflows.engine import (
    NodeExecutionContext,
    NodeResult,
    WorkflowEngineError,
)
from tests.support import activate_admin, activate_user, auth_headers, test_client

# Populated by test_executor_manual_run_scenarios for manual run creation.
WORKSPACE_ID = ""
WORKFLOW_AGENT_ID = ""
ADMIN_USER_ID = ""
WORKFLOW_MODEL_ID = ""
WORKFLOW_DEFINITION_ID = ""


# ---------------------------------------------------------------------------
# workflow_nodes.py helpers
# ---------------------------------------------------------------------------


class _FakeLlmMessage:
    def __init__(
        self,
        text: str,
        tool_calls: list[dict] | None = None,
        usage: dict | None = None,
        additional_kwargs: dict | None = None,
    ) -> None:
        self.text = text
        self.tool_calls = tool_calls or []
        self.invalid_tool_calls = []
        self.response_metadata = {}
        self.usage_metadata = usage or {}
        self.additional_kwargs = additional_kwargs or {}


class _FakeLlmModel:
    def __init__(self, replies: list[_FakeLlmMessage]) -> None:
        self.replies = replies
        self.calls: list[tuple[list, dict]] = []
        self.bound_tools = []

    def bind_tools(self, tools) -> "_FakeLlmModel":
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, **kwargs):
        self.calls.append((list(messages), dict(kwargs)))
        reply = self.replies[0]
        if len(self.replies) > 1:
            self.replies.pop(0)
        return reply


class _FakeWorkflowToolRuntime:
    def __init__(
        self,
        result: AgentToolResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.snapshot = SimpleNamespace(
            tool_id="tool-1",
            version_id="version-1",
            function_name="tool-1",
        )
        self.result = result or AgentToolResult(
            content='{"ok":1}', summary="done", output={"ok": 1}
        )
        self.error = error
        self.calls: list[tuple[str, str, str, dict]] = []

    def get_by_function(self, function_name: str):
        return self.snapshot if function_name == self.snapshot.function_name else None

    def get_by_reference(self, tool_id: str, version_id: str):
        if (tool_id, version_id) != (
            self.snapshot.tool_id,
            self.snapshot.version_id,
        ):
            raise ValueError("Workflow Tool snapshot is unavailable.")
        return self.snapshot

    async def invoke(self, snapshot, node_id, call_id, arguments):
        self.calls.append((snapshot.function_name, node_id, call_id, dict(arguments)))
        if self.error is not None:
            raise self.error
        return self.result


def _node_scope(**overrides) -> SimpleNamespace:
    scope = SimpleNamespace(
        run=SimpleNamespace(
            agent_id="workflow-1",
            model_id="model-1",
            workspace_id="workspace-1",
            goal="g",
        ),
        actor=SimpleNamespace(id="user-1"),
        workspace_role="member",
        settings=None,
        models={"model-1": SimpleNamespace(provider_type="openai_compatible")},
        knowledge_bases={},
        tool_runtime=_FakeWorkflowToolRuntime(),
        node_histories={},
        form_submissions={},
        output_delta=None,
    )
    for key, value in overrides.items():
        setattr(scope, key, value)
    return scope


def _node(node_type: str, config: dict, node_id: str = "n1") -> WorkflowNode:
    return WorkflowNode.model_validate(
        {
            "id": node_id,
            "position": {"x": 0, "y": 0},
            "data": {"type": node_type, "title": node_type, "config": config},
        }
    )


def _context(
    node_outputs: dict | None = None,
    remaining: int = 100,
    workflow_inputs: dict | None = None,
    globals_value: dict | None = None,
) -> NodeExecutionContext:
    return NodeExecutionContext(
        workflow_inputs=workflow_inputs or {},
        node_outputs=node_outputs or {"start": {"question": "hi"}},
        remaining_model_tokens=remaining,
        globals=globals_value
        or {
            "time": "2026-08-13 10:00:00",
            "history_context": [
                {"question": "q1", "answer": "a1"},
                {"question": "q2", "answer": "a2"},
            ],
            "chat_id": "conversation-1",
            "start_time": "2026-08-13T10:00:00+00:00",
        },
    )


# ---------------------------------------------------------------------------
# workflow_nodes.py: pure helpers
# ---------------------------------------------------------------------------


def test_nodes_resolve_value_and_templates() -> None:
    from app.application.workflow_nodes import (
        render_form_template,
        render_reply_template,
        resolve_value,
    )

    context = _context(node_outputs={"start": {"question": "hi", "files": ["f1"]}})
    # non-string passthrough
    assert resolve_value(123, context) == 123
    # dict/list recursion
    assert resolve_value({"a": "{{start.question}}"}, context) == {"a": "hi"}
    assert resolve_value(["{{start.question}}"], context) == ["hi"]
    # full reference match
    assert resolve_value("{{start.question}}", context) == "hi"
    # embedded reference with dict/list serialization
    assert resolve_value("files={{start.files}}", context) == 'files=["f1"]'
    assert resolve_value("files={{global.history_context}}", context) == (
        'files=[{"question":"q1","answer":"a1"},{"question":"q2","answer":"a2"}]'
    )
    # reference to a node that never ran
    try:
        resolve_value("{{missing.x}}", context)
    except ValueError as exc:
        assert "did not run" in str(exc)
    else:
        raise AssertionError("missing node reference was resolved")
    try:
        resolve_value("{{missing}}", context)
    except ValueError as exc:
        assert "did not run" in str(exc)
    else:
        raise AssertionError("missing node reference was resolved")
    # missing path inside an existing node
    try:
        resolve_value("{{start.nope}}", context)
    except ValueError as exc:
        assert "path not found" in str(exc)
    else:
        raise AssertionError("missing path was resolved")

    # reply templates
    rendered = render_reply_template(
        "Hello {{ start.question }}",
        _context(node_outputs={"start": {"question": "world"}}),
    )
    assert rendered == "Hello world"
    try:
        render_reply_template("{% if %}", context)
    except ValueError as exc:
        assert "Invalid workflow reply template" in str(exc)
    else:
        raise AssertionError("malformed reply template was rendered")

    form_context = _context(
        node_outputs={"start": {"question": "q"}},
        globals_value={
            "time": "t",
            "history_context": [],
            "chat_id": "c",
            "start_time": "s",
        },
    )
    assert (
        render_form_template("Before {{ form }} After", form_context)
        == "Before {{ form }} After"
    )
    assert (
        render_form_template("{{ start.question }} then {{ form }}", form_context)
        == "q then {{ form }}"
    )


def test_nodes_reranker_candidates_and_model_params() -> None:
    from app.application.workflow_nodes import (
        _model_call_params,
        _model_output_limit,
        _reranker_candidates,
    )

    candidates, texts = _reranker_candidates(
        [["a"], "plain", {"content": "dict-text"}]
    )
    assert texts == ["a", "plain", "dict-text"]
    try:
        _reranker_candidates([])
    except ValueError as exc:
        assert "non-empty text" in str(exc)
    else:
        raise AssertionError("empty reranker candidates were accepted")
    try:
        _reranker_candidates(["", "x"])
    except ValueError as exc:
        assert "non-empty text" in str(exc)
    else:
        raise AssertionError("empty reranker text was accepted")

    assert _model_output_limit("google_genai", 12) == {"max_output_tokens": 12}
    assert _model_output_limit("ollama", 12) == {"num_predict": 12}
    assert _model_call_params("openai_compatible", {}, 12) == {"max_tokens": 12}
    assert _model_call_params(
        "google_genai",
        {"temperature": 0.5, "top_p": True, "max_tokens": 8},
        12,
    ) == {"max_output_tokens": 8, "temperature": 0.5}
    assert _model_call_params(
        "openai_compatible",
        {"temperature": "hot", "max_tokens": 0},
        12,
    ) == {"max_tokens": 12}


def test_nodes_history_messages_and_invoke() -> None:
    from app.application.workflow_nodes import _history_messages
    from app.schemas.workflow import LlmNodeConfig
    from langchain_core.messages import AIMessage, HumanMessage

    assert _history_messages(
        LlmNodeConfig.model_validate({"prompt": "p", "dialogue_number": 0}),
        _node_scope(),
        _node("llm", {"prompt": "p"}),
        _context(),
    ) == []

    parsed = LlmNodeConfig.model_validate(
        {"prompt": "p", "dialogue_type": "WORKFLOW", "dialogue_number": 5}
    )
    messages = _history_messages(
        parsed,
        _node_scope(),
        _node("llm", {"prompt": "p"}),
        _context(
            globals_value={
                "time": "t",
                "history_context": [
                    {"question": "q1", "answer": "a1"},
                    {"question": "q2", "answer": "a2"},
                    "not-a-dict",
                    {"question": "q", "answer": None},
                ],
                "chat_id": "c",
                "start_time": "s",
            }
        ),
    )
    assert [item.content for item in messages] == ["q1", "a1", "q2", "a2"]
    assert all(
        isinstance(item, (HumanMessage, AIMessage)) for item in messages
    )

    parsed_node = LlmNodeConfig.model_validate(
        {"prompt": "p", "dialogue_type": "NODE", "dialogue_number": 5}
    )
    messages = _history_messages(
        parsed_node,
        _node_scope(
            node_histories={
                "n1": [{"question": "node-q", "answer": "node-a"}]
            }
        ),
        _node("llm", {"prompt": "p"}),
        _context(),
    )
    assert [item.content for item in messages] == ["node-q", "node-a"]


def _legacy_test_nodes_llm_tool_call_and_loop_branches() -> None:
    from unittest.mock import patch

    from app.application.workflow_nodes import execute_workflow_node
    from app.shareddomain.agents.runtime import AgentExecutionPaused

    async def run() -> None:
        # direct _llm_tool_call: malformed JSON and non-dict arguments
        from app.application.workflow_nodes import _llm_tool_call
        from app.ports.llm import ModelToolCall

        tool = SimpleNamespace(name="tool-1", metadata={}, ainvoke=AsyncMock())
        try:
            await _llm_tool_call(
                _node_scope(),
                _node("llm", {"prompt": "p"}),
                tool,  # type: ignore[arg-type]
                ModelToolCall(id="c1", name="tool-1", arguments="not-json{"),
                0,
            )
        except ValueError as exc:
            assert "invalid tool arguments" in str(exc)
        else:
            raise AssertionError("malformed JSON tool arguments were accepted")

        try:
            await _llm_tool_call(
                _node_scope(),
                _node("llm", {"prompt": "p"}),
                tool,  # type: ignore[arg-type]
                ModelToolCall(id="c1", name="tool-1", arguments="[1,2]"),
                0,
            )
        except ValueError as exc:
            assert "invalid tool arguments" in str(exc)
        else:
            raise AssertionError("non-dict tool arguments were accepted")

        # invalid JSON tool arguments through the node
        scope = _node_scope(
            mcp_tools={("srv-1", "tool-1"): ("resolved", "policy")},
        )
        node = _node(
            "llm",
            {
                "prompt": "p",
                "mcp_enable": True,
                "mcp_servers": [{"server_id": "srv-1", "tool_name": "tool-1"}],
            },
        )
        fake = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[{"id": "c1", "name": "tool-1", "args": "not-json"}],
                )
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=fake,
            ),
            patch(
                "app.application.workflow_nodes.build_mcp_agent_tool",
                return_value=SimpleNamespace(
                    name="tool-1", metadata={}, ainvoke=AsyncMock()
                ),
            ),
        ):
            try:
                await execute_workflow_node(scope, node, _context())
            except ValueError as exc:
                assert "invalid tool arguments" in str(exc)
            else:
                raise AssertionError("invalid JSON tool arguments were accepted")

        # non-dict tool arguments
        fake2 = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[{"id": "c1", "name": "tool-1", "args": "[1,2]"}],
                )
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=fake2,
            ),
            patch(
                "app.application.workflow_nodes.build_mcp_agent_tool",
                return_value=SimpleNamespace(
                    name="tool-1", metadata={}, ainvoke=AsyncMock()
                ),
            ),
        ):
            try:
                await execute_workflow_node(scope, node, _context())
            except ValueError as exc:
                assert "invalid tool arguments" in str(exc)
            else:
                raise AssertionError("non-dict tool arguments were accepted")

        # ledger returns a stored result -> tool not invoked again
        stored = AgentToolResult(content="cached", summary="s", output={"ok": 1})

        class StoredLedger:
            def __init__(self) -> None:
                self.after_called = False

            async def before(self, turn, call, metadata, arguments):
                return stored

            async def after(self, turn, call, metadata, arguments, result):
                self.after_called = True

        stored_ledger = StoredLedger()
        scope2 = _node_scope(
            mcp_tools={("srv-1", "tool-1"): ("resolved", "policy")},
            ledger=stored_ledger,
        )
        fake3 = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[{"id": "c1", "name": "tool-1", "args": {"x": 1}}],
                ),
                _FakeLlmMessage("done"),
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=fake3,
            ),
            patch(
                "app.application.workflow_nodes.build_mcp_agent_tool",
                return_value=SimpleNamespace(
                    name="tool-1", metadata={}, ainvoke=AsyncMock()
                ),
            ),
        ):
            result = await execute_workflow_node(scope2, node, _context())
        assert result.outputs == {"text": "done"}
        assert stored_ledger.after_called is False

        # AgentExecutionPaused is surfaced as RuntimeError
        class PausedLedger:
            async def before(self, turn, call, metadata, arguments):
                raise AgentExecutionPaused("call-1", "needs approval")

            async def after(self, turn, call, metadata, arguments, result):
                pass

        scope3 = _node_scope(
            mcp_tools={("srv-1", "tool-1"): ("resolved", "policy")},
            ledger=PausedLedger(),
        )
        fake4 = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[{"id": "c1", "name": "tool-1", "args": {"x": 1}}],
                )
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=fake4,
            ),
            patch(
                "app.application.workflow_nodes.build_mcp_agent_tool",
                return_value=SimpleNamespace(
                    name="tool-1", metadata={}, ainvoke=AsyncMock()
                ),
            ),
        ):
            try:
                await execute_workflow_node(scope3, node, _context())
            except RuntimeError as exc:
                assert "not permitted" in str(exc)
            else:
                raise AssertionError("paused tool call was not rejected")

        # token budget exceeded inside the tool loop
        scope4 = _node_scope(
            mcp_tools={("srv-1", "tool-1"): ("resolved", "policy")},
        )
        fake5 = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[{"id": "c1", "name": "tool-1", "args": {"x": 1}}],
                    usage={"input_tokens": 60, "output_tokens": 50, "total_tokens": 110},
                )
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=fake5,
            ),
            patch(
                "app.application.workflow_nodes.build_mcp_agent_tool",
                return_value=SimpleNamespace(
                    name="tool-1", metadata={}, ainvoke=AsyncMock()
                ),
            ),
        ):
            try:
                await execute_workflow_node(scope4, node, _context())
            except ValueError as exc:
                assert "token budget exceeded" in str(exc)
            else:
                raise AssertionError("token budget overflow was accepted")

        # invalid tool call (missing id)
        fake6 = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[{"id": "", "name": "tool-1", "args": {"x": 1}}],
                )
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=fake6,
            ),
            patch(
                "app.application.workflow_nodes.build_mcp_agent_tool",
                return_value=SimpleNamespace(
                    name="tool-1", metadata={}, ainvoke=AsyncMock()
                ),
            ),
        ):
            try:
                await execute_workflow_node(scope, node, _context())
            except ValueError as exc:
                assert "invalid tool call" in str(exc)
            else:
                raise AssertionError("invalid tool call was accepted")

        # unavailable tool
        fake7 = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[{"id": "c1", "name": "ghost", "args": {"x": 1}}],
                )
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=fake7,
            ),
            patch(
                "app.application.workflow_nodes.build_mcp_agent_tool",
                return_value=SimpleNamespace(
                    name="tool-1", metadata={}, ainvoke=AsyncMock()
                ),
            ),
        ):
            try:
                await execute_workflow_node(scope, node, _context())
            except ValueError as exc:
                assert "unavailable tool" in str(exc)
            else:
                raise AssertionError("unavailable tool call was accepted")

        # tool call limit reached
        scope5 = _node_scope(
            mcp_tools={("srv-1", "tool-1"): ("resolved", "policy")},
        )
        limit_replies = [
            _FakeLlmMessage(
                "",
                tool_calls=[{"id": f"c{index}", "name": "tool-1", "args": {"x": 1}}],
            )
            for index in range(9)
        ]
        fake8 = _FakeLlmModel(limit_replies)
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=fake8,
            ),
            patch(
                "app.application.workflow_nodes.build_mcp_agent_tool",
                return_value=SimpleNamespace(
                    name="tool-1", metadata={}, ainvoke=AsyncMock()
                ),
            ),
        ):
            try:
                await execute_workflow_node(scope5, node, _context())
            except ValueError as exc:
                assert "tool call limit reached" in str(exc)
            else:
                raise AssertionError("tool call limit was not enforced")

    asyncio.run(run())


def test_nodes_llm_tool_call_and_loop_branches() -> None:
    from app.application.workflow_nodes import _llm_tool_call, execute_workflow_node
    from app.ports.llm import ModelToolCall

    async def run() -> None:
        tool = SimpleNamespace(name="tool-1")
        for arguments in ("not-json{", "[1,2]"):
            try:
                await _llm_tool_call(
                    _node_scope(),
                    _node("llm", {"prompt": "p"}),
                    tool,  # type: ignore[arg-type]
                    ModelToolCall(id="c1", name="tool-1", arguments=arguments),
                    0,
                )
            except ValueError as exc:
                assert "invalid tool arguments" in str(exc)
            else:
                raise AssertionError("Invalid model Tool arguments were accepted.")

        node = _node(
            "llm",
            {
                "prompt": "p",
                "tools": [{"tool_id": "tool-1", "version_id": "version-1"}],
            },
        )
        runtime = _FakeWorkflowToolRuntime(
            AgentToolResult(content="cached", summary="done", output={"ok": 1})
        )
        model = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[{"id": "c1", "name": "tool-1", "args": {"x": 1}}],
                ),
                _FakeLlmMessage("done"),
            ]
        )
        with (
            patch("app.application.workflow_nodes.build_chat_model", return_value=model),
            patch(
                "app.application.workflow_nodes.build_unified_agent_tool",
                return_value=tool,
            ),
        ):
            result = await execute_workflow_node(
                _node_scope(tool_runtime=runtime), node, _context()
            )
        assert result.outputs == {"text": "done"}
        assert runtime.calls == [("tool-1", "n1", "llm:0:tool-1", {"x": 1})]

        overflowing = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[{"id": "c1", "name": "tool-1", "args": {}}],
                    usage={"input_tokens": 60, "output_tokens": 50, "total_tokens": 110},
                )
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=overflowing,
            ),
            patch(
                "app.application.workflow_nodes.build_unified_agent_tool",
                return_value=tool,
            ),
        ):
            try:
                await execute_workflow_node(_node_scope(), node, _context())
            except ValueError as exc:
                assert "token budget exceeded" in str(exc)
            else:
                raise AssertionError("Tool-loop token overflow was accepted.")

        invalid_call = _FakeLlmModel(
            [_FakeLlmMessage("", tool_calls=[{"id": "", "name": "tool-1", "args": {}}])]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=invalid_call,
            ),
            patch(
                "app.application.workflow_nodes.build_unified_agent_tool",
                return_value=tool,
            ),
        ):
            try:
                await execute_workflow_node(_node_scope(), node, _context())
            except ValueError as exc:
                assert "invalid tool call" in str(exc)
            else:
                raise AssertionError("Invalid model Tool call was accepted.")

        unavailable = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "", tool_calls=[{"id": "c1", "name": "ghost", "args": {}}]
                )
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=unavailable,
            ),
            patch(
                "app.application.workflow_nodes.build_unified_agent_tool",
                return_value=tool,
            ),
        ):
            try:
                await execute_workflow_node(_node_scope(), node, _context())
            except ValueError as exc:
                assert "unavailable tool" in str(exc)
            else:
                raise AssertionError("Unavailable model Tool was accepted.")

        repeated = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[
                        {"id": f"c{index}", "name": "tool-1", "args": {"x": 1}}
                    ],
                )
                for index in range(9)
            ]
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=repeated,
            ),
            patch(
                "app.application.workflow_nodes.build_unified_agent_tool",
                return_value=tool,
            ),
        ):
            try:
                await execute_workflow_node(_node_scope(), node, _context())
            except ValueError as exc:
                assert "tool call limit reached" in str(exc)
            else:
                raise AssertionError("Model Tool call limit was not enforced.")

    asyncio.run(run())


def test_nodes_llm_stream_and_reasoning_branches() -> None:
    from unittest.mock import patch

    from app.application.workflow_nodes import execute_workflow_node
    from langchain_core.messages import AIMessage, AIMessageChunk

    class StreamingModel(_FakeLlmModel):
        async def astream(self, messages, **kwargs):
            self.calls.append((list(messages), dict(kwargs)))
            yield AIMessageChunk(content="hello ")
            yield AIMessageChunk(content="world")

    class BadStreamingModel(_FakeLlmModel):
        async def astream(self, messages, **kwargs):
            self.calls.append((list(messages), dict(kwargs)))
            yield AIMessage(content="not a chunk")

    async def run() -> None:
        deltas: list[tuple[str, str]] = []

        async def emit(node_id: str, delta: str) -> None:
            deltas.append((node_id, delta))

        scope = _node_scope(output_delta=emit)
        node = _node("llm", {"prompt": "p", "model_id": "model-1"})
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=StreamingModel([_FakeLlmMessage("fallback")]),
        ):
            result = await execute_workflow_node(scope, node, _context())
        assert result.outputs == {"text": "hello world"}
        assert deltas == [("n1", "hello "), ("n1", "world")]

        # a stream message that is not an AIMessageChunk fails the node
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=BadStreamingModel([_FakeLlmMessage("fallback")]),
        ):
            try:
                await execute_workflow_node(scope, node, _context())
            except ValueError as exc:
                assert "invalid stream message" in str(exc)
            else:
                raise AssertionError("invalid stream message was accepted")

        # reasoning_content surfaced when enabled
        fake = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "answer",
                    usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                    additional_kwargs={"reasoning_content": "think step"},
                )
            ]
        )
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=fake,
        ):
            result = await execute_workflow_node(
                _node_scope(),
                _node(
                    "llm",
                    {
                        "prompt": "p",
                        "model_setting": {"reasoning_content_enable": True},
                    },
                ),
                _context(),
            )
        assert result.outputs == {"text": "answer", "reasoning_content": "think step"}

        # model unavailable and exhausted budget
        try:
            await execute_workflow_node(
                _node_scope(models={}),
                _node("llm", {"prompt": "p", "model_id": "missing"}),
                _context(),
            )
        except ValueError as exc:
            assert "model is unavailable" in str(exc)
        else:
            raise AssertionError("unavailable model was accepted")
        try:
            await execute_workflow_node(
                _node_scope(),
                _node("llm", {"prompt": "p"}),
                _context(remaining=0),
            )
        except ValueError as exc:
            assert "token budget exceeded" in str(exc)
        else:
            raise AssertionError("exhausted budget was accepted")

    asyncio.run(run())


def test_nodes_model_result_branches() -> None:
    from unittest.mock import patch

    from app.application.workflow_nodes import _model_result
    from app.ports.llm import RegisteredModel

    async def run() -> None:
        try:
            await _model_result(_node_scope(), "missing", "", "p", 100)
        except ValueError as exc:
            assert "model is unavailable" in str(exc)
        else:
            raise AssertionError("missing model was accepted")

        try:
            await _model_result(_node_scope(), "model-1", "", "p", 0)
        except ValueError as exc:
            assert "token budget exceeded" in str(exc)
        else:
            raise AssertionError("exhausted budget was accepted")

        fake = _FakeLlmModel(
            [_FakeLlmMessage("classified", usage={"total_tokens": 3})]
        )
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=fake,
        ):
            content, usage = await _model_result(
                _node_scope(),
                "model-1",
                "role",
                "p",
                100,
            )
        assert content == "classified"
        assert usage["total_tokens"] == 3
        messages, kwargs = fake.calls[0]
        assert [type(item).__name__ for item in messages] == [
            "SystemMessage",
            "HumanMessage",
        ]

    asyncio.run(run())


def test_nodes_condition_operators() -> None:
    from app.application.workflow_nodes import _condition

    assert _condition(None, "is_null", None)
    assert not _condition("x", "is_null", None)
    assert _condition("x", "is_not_null", None)
    assert not _condition([], "is_not_null", None)
    assert _condition("a", "not_eq", "b")
    assert not _condition("a", "not_eq", "a")
    assert _condition(2, "gt", "1.5")
    assert not _condition(2, "gt", "5")
    # numeric comparison falls back to string ordering
    assert _condition("abc", "ge", "abc")
    assert _condition("abc", "lt", "abd")
    assert _condition("abc", "le", "abc")
    assert not _condition("abd", "le", "abc")
    assert _condition("x", "len_eq", "1")
    assert _condition("ab", "len_ge", "2")
    assert _condition("ab", "len_le", "2")
    assert _condition("ab", "len_lt", "3")
    assert not _condition("ab", "len_gt", "2")
    try:
        _condition("ab", "len_eq", "nope")
    except ValueError as exc:
        assert "non-negative integer" in str(exc)
    else:
        raise AssertionError("non-integer length was accepted")
    try:
        _condition("ab", "len_eq", "-1")
    except ValueError as exc:
        assert "non-negative integer" in str(exc)
    else:
        raise AssertionError("negative length was accepted")
    try:
        _condition("x", "mystery", None)
    except ValueError as exc:
        assert "Unknown workflow condition operator" in str(exc)
    else:
        raise AssertionError("unknown operator was accepted")


def test_nodes_condition_node_no_match() -> None:
    from app.application.workflow_nodes import execute_workflow_node

    async def run() -> None:
        node = _node(
            "condition",
            {
                "branch": [
                    {
                        "id": "only",
                        "type": "IF",
                        "condition": "and",
                        "conditions": [
                            {"field": ["start", "question"], "compare": "eq", "value": "yes"}
                        ],
                    }
                ]
            },
        )
        try:
            await execute_workflow_node(None, node, _context())  # type: ignore[arg-type]
        except ValueError as exc:
            assert "did not match a branch" in str(exc)
        else:
            raise AssertionError("unmatched condition branch was accepted")

    asyncio.run(run())


def test_nodes_template_classifier_reranker_document_knowledge() -> None:
    from unittest.mock import patch

    from app.application.workflow_nodes import execute_workflow_node

    class FakeReranker:
        def rerank(self, query, documents):
            return [
                {"index": 0, "relevance_score": 0.9},
                "not-a-dict",
                {"index": 1, "relevance_score": 0.8},
                {"index": 0, "relevance_score": 0.9},
            ]

    class FakeKnowledgeTool:
        def __init__(self, *, error: bool = False) -> None:
            self.error = error
            self.arguments = None

        async def ainvoke(self, arguments):
            self.arguments = arguments
            if self.error:
                return SimpleNamespace(
                    is_error=True, summary="search exploded", content="", output=None
                )
            return SimpleNamespace(
                is_error=False,
                summary="ok",
                content="",
                output={
                    "hits": [
                        {
                            "content": "alpha",
                            "distance": 0.2,
                            "sources": ["graph"],
                            "graph_claim_ids": ["claim-1"],
                            "graph_hops": 2,
                        },
                        {"content": "beta", "distance": 0.9},
                    ],
                    "graph": {
                        "revision_id": "revision-1",
                        "operation": "path",
                        "paths": [{"steps": [{"claim_id": "claim-1"}]}],
                        "truncated": False,
                    },
                    "evidence_status": "found",
                },
            )

    async def run() -> None:
        # template node
        template = await execute_workflow_node(
            _node_scope(),
            _node("template", {"template": "Hi {{start.question}}"}),
            _context(),
        )
        assert template.outputs == {"text": "Hi hi"}
        assert template.inputs == {"template": "Hi {{start.question}}"}

        # classifier node: recognized handle and default fallback
        classifier_config = {
            "input": "{{start.question}}",
            "classes": [
                {"handle": "yes", "label": "Yes", "description": "affirmative"},
                {"handle": "no", "label": "No", "description": "negative"},
            ],
            "default_handle": "default",
        }
        fake = _FakeLlmModel([_FakeLlmMessage("yes", usage={"total_tokens": 4})])
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=fake,
        ):
            classified = await execute_workflow_node(
                _node_scope(),
                _node("classifier", classifier_config),
                _context(),
            )
        assert classified.outputs == {"class": "yes"}
        assert classified.selected_handles == frozenset({"yes"})
        assert classified.inputs == {"input": "hi", "model_id": "model-1"}
        assert classified.model_tokens == 4

        fake2 = _FakeLlmModel([_FakeLlmMessage("something else")])
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=fake2,
        ):
            classified = await execute_workflow_node(
                _node_scope(),
                _node("classifier", classifier_config),
                _context(),
            )
        assert classified.outputs == {"class": "default"}

        # reranker node
        reranker_context = _context(
            node_outputs={
                "knowledge": {
                    "paragraph_list": [
                        {"content": "first", "document_id": "one"},
                        {"content": "second", "document_id": "two"},
                    ]
                }
            }
        )
        reranker_node = _node(
            "reranker-node",
            {
                "reranker_model_id": "reranker-1",
                "question_reference_address": "question",
                "reranker_reference_list": ["{{knowledge.paragraph_list}}"],
                "reranker_setting": {
                    "top_n": 1,
                    "similarity": 0.5,
                    "max_paragraph_char_number": 10,
                },
            },
        )
        with patch(
            "app.application.workflow_nodes.build_reranker",
            return_value=FakeReranker(),
        ):
            reranked = await execute_workflow_node(
                _node_scope(
                    models={
                        "reranker-1": SimpleNamespace(model_type="RERANKER")
                    }
                ),
                reranker_node,
                reranker_context,
            )
        assert reranked.outputs == {
            "result_list": [{"content": "first", "document_id": "one", "similarity": 0.9}],
            "result": "first",
        }
        # unavailable reranker model
        try:
            await execute_workflow_node(
                _node_scope(models={}),
                reranker_node,
                reranker_context,
            )
        except ValueError as exc:
            assert "reranker model is unavailable" in str(exc)
        else:
            raise AssertionError("unavailable reranker model was accepted")

        # document-extract node
        document = await execute_workflow_node(
            _node_scope(),
            _node(
                "document-extract-node",
                {
                    "document_list": [
                        {"file_id": "file-1", "name": "a.txt", "content": "hello"},
                        {"id": "file-2", "filename": "b.md", "content": "world"},
                    ]
                },
            ),
            _context(),
        )
        assert document.outputs == {
            "content": "--- a.txt ---\nhello\n\n--- b.md ---\nworld"
        }
        assert document.inputs == {"document_count": 2}
        try:
            await execute_workflow_node(
                _node_scope(),
                _node(
                    "document-extract-node",
                    {"document_list": [{"name": "no-id.txt", "content": "x"}]},
                ),
                _context(),
            )
        except ValueError as exc:
            assert "must contain a file id" in str(exc)
        else:
            raise AssertionError("document without file id was accepted")
        try:
            await execute_workflow_node(
                _node_scope(),
                _node(
                    "document-extract-node",
                    {"document_list": [{"file_id": "f", "content": 42}]},
                ),
                _context(),
            )
        except ValueError as exc:
            assert "content is unavailable" in str(exc)
        else:
            raise AssertionError("document without text was accepted")

        # knowledge node: missing base and search failure
        knowledge_node = _node(
            "knowledge",
            {
                "knowledge_base_ids": ["base-1"],
                "query": "question",
                "limit": 2,
                "graph_mode": "path",
                "source_entity": "{{start.question}}",
                "target_entity": "Policy B",
                "max_hops": 4,
                "relation_filters": ["references"],
            },
        )
        try:
            await execute_workflow_node(
                _node_scope(knowledge_bases={}),
                knowledge_node,
                _context(),
            )
        except ValueError as exc:
            assert "knowledge base is unavailable" in str(exc)
        else:
            raise AssertionError("unavailable knowledge base was accepted")

        with patch(
            "app.application.workflow_nodes.build_knowledge_search_tool",
            return_value=FakeKnowledgeTool(error=True),
        ):
            try:
                await execute_workflow_node(
                    _node_scope(
                        knowledge_bases={"base-1": SimpleNamespace(id="base-1")}
                    ),
                    knowledge_node,
                    _context(),
                )
            except RuntimeError as exc:
                assert "search exploded" in str(exc)
            else:
                raise AssertionError("knowledge search error was swallowed")

        fake_knowledge_tool = FakeKnowledgeTool()
        with patch(
            "app.application.workflow_nodes.build_knowledge_search_tool",
            return_value=fake_knowledge_tool,
        ):
            knowledge = await execute_workflow_node(
                _node_scope(
                    knowledge_bases={"base-1": SimpleNamespace(id="base-1")}
                ),
                knowledge_node,
                _context(),
            )
        assert knowledge.outputs["hits"] == [
            {
                "content": "alpha",
                "distance": 0.2,
                "sources": ["graph"],
                "graph_claim_ids": ["claim-1"],
                "graph_hops": 2,
            },
            {"content": "beta", "distance": 0.9},
        ]
        assert knowledge.outputs["content"] == "alpha\n\nbeta"
        assert knowledge.outputs["paragraph_list"][0]["sources"] == ["graph"]
        assert knowledge.outputs["paragraph_list"][0]["graph_claim_ids"] == [
            "claim-1"
        ]
        assert knowledge.outputs["graph_revision_id"] == "revision-1"
        assert knowledge.outputs["graph_paths"] == [
            {"steps": [{"claim_id": "claim-1"}]}
        ]
        assert fake_knowledge_tool.arguments == {
            "query": "question",
            "limit": 2,
            "search_mode": "embedding",
            "similarity": 0.6,
            "graph_mode": "path",
            "source_entity": "hi",
            "target_entity": "Policy B",
            "max_hops": 4,
            "relation_filters": ["references"],
        }
        assert knowledge.inputs["graph_mode"] == "path"
        assert knowledge.inputs["source_entity"] == "hi"

    asyncio.run(run())


def _legacy_test_nodes_mcp_and_code_and_unsupported() -> None:
    from unittest.mock import patch

    from app.application.workflow_nodes import execute_workflow_node
    from app.infrastructure.code_sandbox import WorkflowSandboxResult
    from app.shareddomain.agents.runtime import AgentExecutionPaused

    async def run() -> None:
        fake_tool = SimpleNamespace(
            name="search",
            metadata={},
            ainvoke=AsyncMock(
                return_value=AgentToolResult(
                    content="hits", summary="s", output={"found": 3}
                )
            ),
        )
        mcp_node = _node(
            "mcp",
            {
                "server_id": "srv-1",
                "tool_name": "search",
                "arguments": {"query": "{{start.question}}"},
            },
            node_id="mcp-1",
        )
        ledger = _FakeLlmLedger()
        scope = _node_scope(
            mcp_tools={("srv-1", "search"): ("resolved", "policy")},
            ledger=ledger,
        )
        with patch(
            "app.application.workflow_nodes.build_mcp_agent_tool",
            return_value=fake_tool,
        ):
            result = await execute_workflow_node(scope, mcp_node, _context())
        assert result.outputs == {"found": 3}
        assert ledger.calls[0][:3] == ("before", 3, "workflow-mcp-1")
        assert ledger.calls[1][0] == "after"

        # unavailable mcp tool
        try:
            await execute_workflow_node(
                _node_scope(),
                mcp_node,
                _context(),
            )
        except ValueError as exc:
            assert "unavailable or not read-only" in str(exc)
        else:
            raise AssertionError("unavailable mcp tool was accepted")

        # error result from the mcp tool
        fake_error_tool = SimpleNamespace(
            name="search",
            metadata={},
            ainvoke=AsyncMock(
                return_value=AgentToolResult(
                    content="", summary="denied", output=None, is_error=True
                )
            ),
        )
        with patch(
            "app.application.workflow_nodes.build_mcp_agent_tool",
            return_value=fake_error_tool,
        ):
            try:
                await execute_workflow_node(
                    _node_scope(
                        mcp_tools={("srv-1", "search"): ("resolved", "policy")}
                    ),
                    mcp_node,
                    _context(),
                )
            except RuntimeError as exc:
                assert "denied" in str(exc)
            else:
                raise AssertionError("mcp error result was swallowed")

        # paused mcp call
        class PausedLedger:
            async def before(self, turn, call, metadata, arguments):
                raise AgentExecutionPaused("mcp-call", "policy changed")

            async def after(self, turn, call, metadata, arguments, result):
                pass

        with patch(
            "app.application.workflow_nodes.build_mcp_agent_tool",
            return_value=fake_tool,
        ):
            try:
                await execute_workflow_node(
                    _node_scope(
                        mcp_tools={("srv-1", "search"): ("resolved", "policy")},
                        ledger=PausedLedger(),
                    ),
                    mcp_node,
                    _context(),
                )
            except RuntimeError as exc:
                assert "read-only policy" in str(exc)
            else:
                raise AssertionError("paused mcp call was accepted")

        # code node
        code_node = _node(
            "code",
            {
                "code": "result = {'sum': inputs['a'] + inputs['b']}",
                "inputs": {"a": 1, "b": 2},
            },
            node_id="code-1",
        )
        with patch(
            "app.application.workflow_nodes.execute_workflow_code",
            new=AsyncMock(
                return_value=WorkflowSandboxResult(
                    result={"sum": 3}, stdout="ok", stderr="", exit_code=0
                )
            ),
        ):
            coded = await execute_workflow_node(_node_scope(), code_node, _context())
        assert coded.outputs == {"result": {"sum": 3}, "stdout": "ok", "stderr": ""}
        assert coded.inputs == {"a": 1, "b": 2}

        # unsupported node type (constructed outside schema validation)
        from app.schemas.workflow import WorkflowNode as NodeSchema
        from app.schemas.workflow import WorkflowNodeData

        bogus = NodeSchema.model_construct(
            id="bogus",
            position={"x": 0, "y": 0},
            data=WorkflowNodeData.model_construct(
                type="bogus-node", title="bogus", config={}
            ),
        )
        try:
            await execute_workflow_node(_node_scope(), bogus, _context())
        except ValueError as exc:
            assert "Unsupported workflow node type" in str(exc)
        else:
            raise AssertionError("unsupported node type was accepted")

    asyncio.run(run())


def test_nodes_tool_and_unsupported() -> None:
    from app.application.workflow_nodes import execute_workflow_node

    async def run() -> None:
        node = _node(
            "tool",
            {
                "tool": {"tool_id": "tool-1", "version_id": "version-1"},
                "arguments": {"query": "{{start.question}}"},
            },
            node_id="tool-1",
        )
        runtime = _FakeWorkflowToolRuntime(
            AgentToolResult(content="hits", summary="done", output={"found": 3})
        )
        result = await execute_workflow_node(
            _node_scope(tool_runtime=runtime), node, _context()
        )
        assert result.inputs == {"query": "hi"}
        assert result.outputs == {"found": 3}
        assert runtime.calls == [
            ("tool-1", "tool-1", "direct", {"query": "hi"})
        ]

        error_runtime = _FakeWorkflowToolRuntime(
            AgentToolResult(
                content="",
                summary="denied",
                output=None,
                is_error=True,
            )
        )
        try:
            await execute_workflow_node(
                _node_scope(tool_runtime=error_runtime), node, _context()
            )
        except RuntimeError as exc:
            assert "denied" in str(exc)
        else:
            raise AssertionError("Workflow Tool error was swallowed.")

        inline = _node(
            "tool",
            {
                "tool": {"tool_id": "tool-1", "version_id": "version-1"},
                "arguments": {
                    "code": "result = inputs",
                    "inputs": {"a": 1},
                },
            },
            node_id="python-1",
        )
        inline_runtime = _FakeWorkflowToolRuntime(
            AgentToolResult(
                content='{"result":{"a":1}}',
                summary="done",
                output={"result": {"a": 1}},
            )
        )
        coded = await execute_workflow_node(
            _node_scope(tool_runtime=inline_runtime), inline, _context()
        )
        assert coded.outputs == {"result": {"a": 1}}

        from app.schemas.workflow import WorkflowNode as NodeSchema
        from app.schemas.workflow import WorkflowNodeData

        bogus = NodeSchema.model_construct(
            id="bogus",
            position={"x": 0, "y": 0},
            data=WorkflowNodeData.model_construct(
                type="bogus-node", title="bogus", config={}
            ),
        )
        try:
            await execute_workflow_node(_node_scope(), bogus, _context())
        except ValueError as exc:
            assert "Unsupported workflow node type" in str(exc)
        else:
            raise AssertionError("Unsupported Workflow node was accepted.")

    asyncio.run(run())


def test_nodes_engine_resume_with_form_submission() -> None:
    """Form node pause/resume through the engine (workflow_nodes form branch)."""
    from app.application.workflow_nodes import execute_workflow_node

    form_config = {
        "form_field_list": [
            {"variable": "email", "name": "Email", "type": "input", "is_required": True}
        ],
        "form_content_format": "Send to {{ start.question }} then {{ form }}",
    }

    async def run() -> None:
        form = _node("form-node", form_config)
        scope = _node_scope()
        waiting = await execute_workflow_node(scope, form, _context())
        assert waiting.interrupt is not None
        assert waiting.interrupt["runtime_node_id"] == "n1"
        assert waiting.interrupt["content"] == "Send to hi then {{ form }}"
        scope.form_submissions["n1"] = {"email": "user@example.com"}
        submitted = await execute_workflow_node(scope, form, _context())
        assert submitted.outputs["email"] == "user@example.com"
        assert submitted.outputs["result"] == '{"email":"user@example.com"}'

    asyncio.run(run())


# ---------------------------------------------------------------------------
# workflow_executor.py unit tests
# ---------------------------------------------------------------------------


def test_executor_safe_errors_and_run_error() -> None:
    from app.application.workflow_executor import (
        _safe_node_error,
        _safe_run_error,
    )
    from app.infrastructure.code_sandbox import WorkflowSandboxError
    from app.ports.llm import ModelProviderError, ModelProviderTimeoutError

    assert (
        _safe_node_error(ModelProviderTimeoutError("timeout"))
        == "Workflow model request timed out."
    )
    assert (
        _safe_node_error(ModelProviderError("failed"))
        == "Workflow model request failed."
    )
    assert _safe_node_error(WorkflowSandboxError("sandbox boom")) == "sandbox boom"
    assert _safe_node_error(ValueError("value boom")) == "value boom"
    assert _safe_node_error(KeyError("k")) == "Workflow node execution failed."
    assert _safe_run_error(WorkflowEngineError("engine boom")) == "engine boom"
    assert _safe_run_error(KeyError("k")) == "Workflow execution failed."


def test_executor_workflow_context_branches() -> None:
    from app.application.workflow_executor import _workflow_context
    from app.schemas.workflow import WorkflowGraph

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    prior = [
        SimpleNamespace(id="run-new", goal="new", result='{"value":"new"}'),
        SimpleNamespace(id="run-old", goal="old", result="old answer"),
        SimpleNamespace(id="run-plain", goal="plain", result="not-json {"),
    ]
    executions = [
        SimpleNamespace(
            run_id="run-new",
            node_id="llm-1",
            status="succeeded",
            outputs={"text": "new node answer"},
        ),
        SimpleNamespace(
            run_id="run-old",
            node_id="start",
            status="succeeded",
            outputs={"text": "ignored node"},
        ),
        SimpleNamespace(
            run_id="run-old",
            node_id="llm-1",
            status="failed",
            outputs={"text": "failed node"},
        ),
        SimpleNamespace(
            run_id="run-plain",
            node_id="llm-1",
            status="succeeded",
            outputs={"other": "no text"},
        ),
        SimpleNamespace(
            run_id="run-new",
            node_id="llm-1",
            status="succeeded",
            outputs={"text": "second answer"},
        ),
    ]
    run = SimpleNamespace(
        agent_id="agent-1",
        access_source="console",
        consumer_id="user-1",
        conversation_id="conversation-1",
    )
    workflow = WorkflowGraph.model_validate(
        {
            "nodes": [
                {
                    "id": "llm-1",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "llm",
                        "title": "LLM",
                        "config": {"prompt": "question", "dialogue_type": "NODE"},
                    },
                }
            ],
            "edges": [],
        }
    )

    async def check() -> None:
        with patch(
            "app.application.workflow_executor.get_session_factory",
            return_value=lambda: SessionContext(),
        ), patch(
            "app.application.workflow_executor.agent_repository.list_agent_runs",
            new=AsyncMock(return_value=prior),
        ), patch(
            "app.application.workflow_executor.workflow_repository."
            "list_node_executions_for_runs",
            new=AsyncMock(return_value=executions),
        ):
            workflow_globals, histories = await _workflow_context(
                run,  # type: ignore[arg-type]
                workflow,
            )

        assert workflow_globals["history_context"] == [
            {"question": "plain", "answer": "not-json {"},
            {"question": "old", "answer": "old answer"},
            {"question": "new", "answer": {"value": "new"}},
        ]
        assert histories == {
            "llm-1": [
                {"question": "new", "answer": "new node answer"},
                {"question": "new", "answer": "second answer"},
            ]
        }

        # no conversation -> no database access
        run_no_conv = SimpleNamespace(
            agent_id="agent-1",
            access_source="console",
            consumer_id="user-1",
            conversation_id=None,
        )
        workflow_globals, histories = await _workflow_context(
            run_no_conv,  # type: ignore[arg-type]
            workflow,
        )
        assert workflow_globals["history_context"] == []
        assert histories == {"llm-1": []}

    asyncio.run(check())


def test_executor_load_scope_branches() -> None:
    from app.application import workflow_executor as executor_module
    from app.entities.agents import AgentRun
    from app.entities.workflows import WorkflowRunDetail
    from app.infrastructure.repositories import (
        agent as agent_repository,
        user as user_repository,
        workflow as workflow_repository,
    )
    from app.shareddomain.workflows.resources import (
        build_workflow_resource_snapshot,
        workflow_resource_hash,
    )

    class SessionContext:
        def __init__(self, db):
            self.db = db

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *_args):
            return None

    def graph_snapshot() -> dict:
        return {
            "nodes": [
                {
                    "id": "start",
                    "type": "workflow",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "start", "title": "Start", "config": {}},
                }
            ],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }

    run = AgentRun(
        id="run-1",
        workspace_id="ws-1",
        agent_id="agent-1",
        execution_user_id="user-1",
        status="running",
        model_id="model-1",
        conversation_id=None,
        knowledge_base_ids=[],
        mcp_tools=[],
        model_usage={},
    )
    resource_snapshot = build_workflow_resource_snapshot([], [])
    detail = WorkflowRunDetail(
        run_id="run-1",
        workspace_id="ws-1",
        graph_snapshot=graph_snapshot(),
        resource_snapshot=resource_snapshot,
        resource_hash=workflow_resource_hash(resource_snapshot),
        inputs={"question": "q"},
        max_steps=10,
        max_model_tokens=1000,
        deadline_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    agent = SimpleNamespace(app_type="workflow", status="active")
    actor = SimpleNamespace(is_active=True, id="user-1")
    workspace = SimpleNamespace(membership_role="member")

    async def scope(**overrides) -> executor_module.WorkflowExecutionScope:
        db = object()
        with patch(
            "app.application.workflow_executor.get_session_factory",
            return_value=lambda: SessionContext(db),
        ), patch.object(
            agent_repository,
            "get_agent_run_by_id",
            new=AsyncMock(return_value=overrides.get("run", run)),
        ), patch.object(
            workflow_repository,
            "get_run_detail",
            new=AsyncMock(return_value=overrides.get("detail", detail)),
        ), patch.object(
            agent_repository,
            "get_agent_by_id",
            new=AsyncMock(return_value=overrides.get("agent", agent)),
        ), patch.object(
            user_repository,
            "get_user_by_id",
            new=AsyncMock(return_value=overrides.get("actor", actor)),
        ), patch(
            "app.application.workflow_executor.build_workspace_context",
            new=AsyncMock(return_value=overrides.get("workspace", workspace)),
        ), patch(
            "app.application.workflow_executor.get_agent_model",
            new=AsyncMock(return_value=SimpleNamespace(provider_type="openai_compatible")),
        ), patch(
            "app.application.workflow_executor.accessible_agent_knowledge_bases",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.application.workflow_executor.get_registered_model_by_id",
            new=AsyncMock(return_value=overrides.get("reranker_model")),
        ):
            return await executor_module._load_scope("run-1")

    async def check() -> None:
        # missing detail
        try:
            await scope(detail=None)
        except WorkflowEngineError as exc:
            assert "not executable" in str(exc)
        else:
            raise AssertionError("missing detail was accepted")
        # unavailable agent
        try:
            await scope(agent=None)
        except WorkflowEngineError as exc:
            assert "unavailable" in str(exc)
        else:
            raise AssertionError("missing agent was accepted")
        # inactive actor
        try:
            await scope(actor=SimpleNamespace(is_active=False))
        except WorkflowEngineError as exc:
            assert "user is unavailable" in str(exc)
        else:
            raise AssertionError("inactive actor was accepted")
        # unavailable reranker model
        reranker_graph = graph_snapshot()
        reranker_graph["nodes"].append(
            {
                "id": "reranker",
                "type": "workflow",
                "position": {"x": 100, "y": 0},
                "data": {
                    "type": "reranker-node",
                    "title": "Reranker",
                    "config": {
                        "reranker_model_id": "rr-1",
                        "question_reference_address": "question",
                        "reranker_reference_list": ["{{start.question}}"],
                    },
                },
            }
        )
        reranker_detail = WorkflowRunDetail(
            run_id="run-1",
            workspace_id="ws-1",
            graph_snapshot=reranker_graph,
            resource_snapshot=resource_snapshot,
            resource_hash=workflow_resource_hash(resource_snapshot),
            deadline_at=detail.deadline_at,
        )
        try:
            await scope(detail=reranker_detail, reranker_model=None)
        except WorkflowEngineError as exc:
            assert "reranker model is unavailable" in str(exc)
        else:
            raise AssertionError("unavailable reranker model was accepted")

        # reranker node with a valid model
        valid_model = SimpleNamespace(
            workspace_id="ws-1",
            model_type="RERANKER",
            status="active",
            provider_type="openai_compatible",
        )
        loaded = await scope(
            detail=reranker_detail,
            reranker_model=valid_model,
        )
        assert "rr-1" in loaded.models

        assert loaded.tool_snapshots == []

        inconsistent = AgentRun(**{**run.__dict__, "tool_snapshots": [{}]})
        try:
            await scope(run=inconsistent)
        except WorkflowEngineError as exc:
            assert "snapshot is inconsistent" in str(exc)
        else:
            raise AssertionError("Inconsistent Workflow Tool snapshot was accepted.")

    asyncio.run(check())


# ---------------------------------------------------------------------------
# executor integration tests (manual runs against the real test database)
# ---------------------------------------------------------------------------


class _FakeUploadStorage:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.keys: list[str] = []
        self.put_calls = 0

    async def put_chunks(self, key, chunks, max_bytes=None):
        self.put_calls += 1
        if self.error is not None:
            raise self.error
        size = 0
        async for chunk in chunks:
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                from app.infrastructure.object_storage import ObjectTooLargeError

                raise ObjectTooLargeError("too large")
        self.keys.append(key)
        return size

    def delete(self, key):
        if key in self.keys:
            self.keys.remove(key)

    def path(self, key):
        return f"/tmp/fake/{key}"


def _upload_file(filename: str, content: bytes = b"hello") -> object:
    from fastapi import UploadFile

    return UploadFile(filename=filename, file=io.BytesIO(content))


def test_workflow_uploads_upload_branches() -> None:
    import app.application.workflow_uploads as uploads_module
    from app.application.workflow_uploads import _upload_files
    from app.entities.workflows import WorkflowUpload
    from app.infrastructure.object_storage import EmptyObjectError
    from fastapi import HTTPException
    from app.schemas.agent import AgentInteractionConfig

    agent = SimpleNamespace(workspace_id="ws-1", id="agent-1")
    config = AgentInteractionConfig.model_validate(
        {
            "file_upload": True,
            "file_upload_setting": {"file_upload_type": ["document"]},
        }
    )
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    def storage_patch(fake: _FakeUploadStorage):
        return patch(
            "app.application.workflow_uploads.create_object_storage",
            return_value=fake,
        )

    async def upload(**overrides) -> list[WorkflowUpload]:
        return await _upload_files(
            overrides.get("db", db),
            overrides.get("agent", agent),
            overrides.get("user_id", "user-1"),
            overrides.get("uploads", [_upload_file("notes.txt")]),
            overrides.get("settings", SimpleNamespace(knowledge_storage_dir="/tmp/x")),
            overrides.get("config", config),
            overrides.get("application_type", "workflow"),
        )

    async def run() -> None:
        # uploads disabled
        disabled = AgentInteractionConfig.model_validate(
            {"file_upload": False}
        )
        with patch(
            "app.application.workflow_uploads.create_object_storage"
        ):
            try:
                await upload(config=disabled)
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("disabled uploads were accepted")

        # empty uploads
        with storage_patch(_FakeUploadStorage()):
            try:
                await upload(uploads=[])
            except HTTPException as exc:
                assert exc.status_code == 422
            else:
                raise AssertionError("empty uploads were accepted")

        # workspace lock missing
        with storage_patch(_FakeUploadStorage()), patch(
            "app.application.workflow_uploads.workspace_repository.lock_workspace",
            new=AsyncMock(return_value=None),
        ):
            try:
                await upload()
            except HTTPException as exc:
                assert exc.status_code == 404
                assert "workspace" in str(exc.detail)
            else:
                raise AssertionError("missing workspace was accepted")

        # user lock missing
        with storage_patch(_FakeUploadStorage()), patch(
            "app.application.workflow_uploads.workspace_repository.lock_workspace",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.user_repository.lock_user",
            new=AsyncMock(return_value=None),
        ):
            try:
                await upload()
            except HTTPException as exc:
                assert exc.status_code == 404
                assert "user" in str(exc.detail)
            else:
                raise AssertionError("missing user was accepted")

        # application lock missing
        with storage_patch(_FakeUploadStorage()), patch(
            "app.application.workflow_uploads.workspace_repository.lock_workspace",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.user_repository.lock_user",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.workflow_repository."
            "lock_upload_application",
            new=AsyncMock(return_value=False),
        ):
            try:
                await upload()
            except HTTPException as exc:
                assert exc.status_code == 404
                assert "application" in str(exc.detail)
            else:
                raise AssertionError("missing application was accepted")

        # unsupported upload type
        with storage_patch(_FakeUploadStorage()), patch(
            "app.application.workflow_uploads.workspace_repository.lock_workspace",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.user_repository.lock_user",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.workflow_repository."
            "lock_upload_application",
            new=AsyncMock(return_value=True),
        ):
            try:
                await upload(uploads=[_upload_file("evil.exe")])
            except HTTPException as exc:
                assert exc.status_code == 422
                assert "Unsupported" in str(exc.detail)
            else:
                raise AssertionError("unsupported type was accepted")

        # file-count limit is enforced before any object is written
        fake = _FakeUploadStorage()
        with storage_patch(fake), patch.object(
            uploads_module,
            "MAX_WORKFLOW_UPLOAD_FILES",
            10,
            create=True,
        ), patch(
            "app.application.workflow_uploads.workspace_repository.lock_workspace",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.user_repository.lock_user",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.workflow_repository."
            "lock_upload_application",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.application.workflow_uploads.workflow_repository.create_upload",
            new=AsyncMock(side_effect=lambda db_session, item: item),
        ):
            try:
                await upload(uploads=[_upload_file(f"{index}.txt") for index in range(11)])
            except HTTPException as exc:
                assert exc.status_code == 413
            else:
                raise AssertionError("too many upload files were accepted")
        assert fake.put_calls == 0

        # total request bytes are shared across every file in the request
        fake = _FakeUploadStorage()
        with storage_patch(fake), patch.object(
            uploads_module,
            "MAX_WORKFLOW_UPLOAD_BYTES",
            8,
            create=True,
        ), patch(
            "app.application.workflow_uploads.workspace_repository.lock_workspace",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.user_repository.lock_user",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.workflow_repository."
            "lock_upload_application",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.application.workflow_uploads.workflow_repository.create_upload",
            new=AsyncMock(side_effect=lambda db_session, item: item),
        ):
            try:
                await upload(
                    uploads=[
                        _upload_file("a.txt", b"12345"),
                        _upload_file("b.txt", b"67890"),
                    ]
                )
            except HTTPException as exc:
                assert exc.status_code == 413
            else:
                raise AssertionError("oversized upload request was accepted")
        assert fake.keys == []

        # empty object -> rollback + delete
        fake = _FakeUploadStorage(EmptyObjectError("empty"))
        with storage_patch(fake), patch(
            "app.application.workflow_uploads.workspace_repository.lock_workspace",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.user_repository.lock_user",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.workflow_repository."
            "lock_upload_application",
            new=AsyncMock(return_value=True),
        ):
            try:
                await upload(uploads=[_upload_file("a.txt"), _upload_file("b.txt")])
            except HTTPException as exc:
                assert exc.status_code == 422
                assert "empty" in str(exc.detail)
            else:
                raise AssertionError("empty object upload was accepted")
        assert db.rollback.await_count >= 1
        assert fake.keys == []

        # unexpected error -> rollback + delete + re-raise
        fake = _FakeUploadStorage(ValueError("disk full"))
        with storage_patch(fake), patch(
            "app.application.workflow_uploads.workspace_repository.lock_workspace",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.user_repository.lock_user",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.workflow_repository."
            "lock_upload_application",
            new=AsyncMock(return_value=True),
        ):
            try:
                await upload(uploads=[_upload_file("a.txt")])
            except ValueError as exc:
                assert "disk full" in str(exc)
            else:
                raise AssertionError("storage failure was swallowed")
        assert fake.keys == []

        # happy path with two files
        fake = _FakeUploadStorage()
        create_upload = AsyncMock(
            side_effect=lambda db_session, item: item
        )
        with storage_patch(fake), patch(
            "app.application.workflow_uploads.workspace_repository.lock_workspace",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.user_repository.lock_user",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.application.workflow_uploads.workflow_repository."
            "lock_upload_application",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.application.workflow_uploads.workflow_repository.create_upload",
            new=create_upload,
        ):
            stored = await upload(
                uploads=[
                    _upload_file("a.txt", b"one"),
                    _upload_file("b.PDF", b"two more"),
                ]
            )
        assert [item.filename for item in stored] == ["a.txt", "b.PDF"]
        assert [item.category for item in stored] == ["document", "document"]
        assert stored[0].content_type == "application/octet-stream"
        assert stored[1].content_type == "application/octet-stream"
        assert stored[0].size_bytes == 3
        assert stored[1].size_bytes == 8
        assert len(fake.keys) == 2
        assert fake.keys[0].startswith("workflow-uploads/ws-1/agent-1/user-1/")
        assert db.commit.await_count >= 1

    asyncio.run(run())


def test_workflow_uploads_resolve_branches() -> None:
    _UPLOAD_SETTINGS = SimpleNamespace(knowledge_storage_dir="/tmp/x")
    from app.application.workflow_uploads import (
        _resolve_agent_file_text,
        _resolve_workflow_files,
    )
    from app.entities.workflows import WorkflowUpload
    from app.infrastructure.object_storage import EmptyObjectError
    from fastapi import HTTPException
    from app.schemas.agent import AgentInteractionConfig

    agent = SimpleNamespace(workspace_id="ws-1", id="agent-1")
    config = AgentInteractionConfig.model_validate(
        {
            "file_upload": True,
            "file_upload_setting": {"file_upload_type": ["document"]},
        }
    )
    db = SimpleNamespace()

    def uploads(items: list[WorkflowUpload]) -> list[WorkflowUpload]:
        return items

    def make_upload(upload_id: str, category: str = "document") -> WorkflowUpload:
        return WorkflowUpload(
            id=upload_id,
            workspace_id="ws-1",
            agent_id="agent-1",
            uploaded_by_user_id="user-1",
            filename=f"{upload_id}.txt",
            content_type="text/plain",
            size_bytes=3,
            category=category,
            object_key=f"workflow-uploads/ws-1/agent-1/user-1/{upload_id}",
        )

    class FakeParser:
        def __init__(self, text: str, error: bool = False) -> None:
            self.text = text
            self.error = error

        def extract(self, filename, content_type, path):
            if self.error:
                from app.ports.parsing import KnowledgePipelineError

                raise KnowledgePipelineError("cannot parse")
            return self.text, []

    async def run() -> None:
        # empty file ids
        result = await _resolve_workflow_files(
            db, agent, "user-1", [], config, _UPLOAD_SETTINGS,  # type: ignore[arg-type]
            extract_text=False,
        )
        assert result == []

        # uploads disabled
        disabled = AgentInteractionConfig.model_validate({"file_upload": False})
        try:
            await _resolve_workflow_files(
                db, agent, "user-1", ["u1"], disabled, _UPLOAD_SETTINGS,  # type: ignore[arg-type]
                extract_text=False,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("disabled file resolution was accepted")

        # duplicate ids
        try:
            await _resolve_workflow_files(
                db, agent, "user-1", ["u1", "u1"], config, _UPLOAD_SETTINGS,  # type: ignore[arg-type]
                extract_text=False,
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("duplicate file ids were accepted")

        # upload not found
        with patch(
            "app.application.workflow_uploads.workflow_repository.list_uploads",
            new=AsyncMock(return_value=[]),
        ):
            try:
                await _resolve_workflow_files(
                    db, agent, "user-1", ["u1"], config, _UPLOAD_SETTINGS,  # type: ignore[arg-type]
                    extract_text=False,
                )
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("missing upload was accepted")

        # happy path without extraction
        consume = AsyncMock()
        with patch(
            "app.application.workflow_uploads.workflow_repository.list_uploads",
            new=AsyncMock(return_value=uploads([make_upload("u1")])),
        ), patch(
            "app.application.workflow_uploads.queue_upload_cleanups",
            new=consume,
        ):
            result = await _resolve_workflow_files(
                db, agent, "user-1", ["u1"], config, _UPLOAD_SETTINGS,  # type: ignore[arg-type]
                extract_text=False,
            )
        assert result == [
            {
                "id": "u1",
                "name": "u1.txt",
                "content_type": "text/plain",
                "size_bytes": 3,
                "category": "document",
            }
        ]
        consume.assert_awaited_once()

        # extraction happy path (three files to exhaust the bounded context)
        three = [make_upload(f"u{index}") for index in range(3)]
        with patch(
            "app.application.workflow_uploads.workflow_repository.list_uploads",
            new=AsyncMock(return_value=uploads(three)),
        ), patch(
            "app.application.workflow_uploads.build_document_parser",
            return_value=FakeParser("x" * 60000),
        ), patch(
            "app.application.workflow_uploads.create_object_storage",
            return_value=_FakeUploadStorage(),
        ), patch(
            "app.application.workflow_uploads.queue_upload_cleanups",
            new=AsyncMock(),
        ):
            result = await _resolve_workflow_files(
                db, agent, "user-1", ["u0", "u1", "u2"], config, _UPLOAD_SETTINGS,  # type: ignore[arg-type]
                extract_text=True,
            )
        assert [item["file_id"] for item in result] == ["u0", "u1", "u2"]
        assert len(result[0]["content"]) == 20000
        assert len(result[1]["content"]) == 20000
        assert len(result[2]["content"]) == 10000

        # extraction failure
        with patch(
            "app.application.workflow_uploads.workflow_repository.list_uploads",
            new=AsyncMock(return_value=uploads([make_upload("u1")])),
        ), patch(
            "app.application.workflow_uploads.build_document_parser",
            return_value=FakeParser("", error=True),
        ), patch(
            "app.application.workflow_uploads.create_object_storage",
            return_value=_FakeUploadStorage(),
        ):
            try:
                await _resolve_workflow_files(
                    db, agent, "user-1", ["u1"], config, _UPLOAD_SETTINGS,  # type: ignore[arg-type]
                    extract_text=True,
                )
            except HTTPException as exc:
                assert exc.status_code == 422
                assert "could not be extracted" in str(exc.detail)
            else:
                raise AssertionError("extraction failure was swallowed")

        # agent text resolution
        text, attachments = await _resolve_agent_file_text(
            db, agent, "user-1", [], _UPLOAD_SETTINGS  # type: ignore[arg-type]
        )
        assert text == ""
        assert attachments == []
        try:
            await _resolve_agent_file_text(
                db, agent, "user-1", ["u1", "u1"], _UPLOAD_SETTINGS  # type: ignore[arg-type]
            )
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError("duplicate agent files were accepted")
        with patch(
            "app.application.workflow_uploads.workflow_repository.list_uploads",
            new=AsyncMock(return_value=[]),
        ):
            try:
                await _resolve_agent_file_text(
                    db, agent, "user-1", ["u1"], _UPLOAD_SETTINGS  # type: ignore[arg-type]
                )
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("missing agent upload was accepted")
        with patch(
            "app.application.workflow_uploads.workflow_repository.list_uploads",
            new=AsyncMock(return_value=uploads([make_upload("u1")])),
        ), patch(
            "app.application.workflow_uploads.build_document_parser",
            return_value=FakeParser("agent text"),
        ), patch(
            "app.application.workflow_uploads.create_object_storage",
            return_value=_FakeUploadStorage(),
        ), patch(
            "app.application.workflow_uploads.queue_upload_cleanups",
            new=AsyncMock(),
        ):
            text, attachments = await _resolve_agent_file_text(
                db, agent, "user-1", ["u1"], _UPLOAD_SETTINGS  # type: ignore[arg-type]
            )
        assert text == "--- u1.txt ---\nagent text"
        assert attachments == [
            {
                "filename": "u1.txt",
                "content_type": "text/plain",
                "size_bytes": 3,
                "category": "document",
            }
        ]
        with patch(
            "app.application.workflow_uploads.workflow_repository.list_uploads",
            new=AsyncMock(return_value=uploads([make_upload("u1")])),
        ), patch(
            "app.application.workflow_uploads.build_document_parser",
            return_value=FakeParser("", error=True),
        ), patch(
            "app.application.workflow_uploads.create_object_storage",
            return_value=_FakeUploadStorage(),
        ):
            try:
                await _resolve_agent_file_text(
                    db, agent, "user-1", ["u1"], _UPLOAD_SETTINGS  # type: ignore[arg-type]
                )
            except HTTPException as exc:
                assert exc.status_code == 422
                assert "could not be extracted" in str(exc.detail)
            else:
                raise AssertionError("agent extraction failure was swallowed")

        # agent upload policy validation: image category not allowed for agents
        with patch(
            "app.application.workflow_uploads.workflow_repository.list_uploads",
            new=AsyncMock(return_value=uploads([make_upload("img", category="image")])),
        ):
            try:
                await _resolve_workflow_files(
                    db, agent, "user-1", ["img"], config, _UPLOAD_SETTINGS,  # type: ignore[arg-type]
                    extract_text=False,
                )
            except HTTPException as exc:
                assert exc.status_code == 422
            else:
                raise AssertionError("policy mismatch was accepted")

    asyncio.run(run())


def test_workflow_uploads_workspace_wrappers() -> None:
    from app.application.workflow_uploads import (
        resolve_workspace_agent_files,
        resolve_workspace_workflow_files,
        upload_workspace_agent_files,
        upload_workspace_workflow_files,
    )
    from app.entities.workflows import WorkflowUpload

    agent = SimpleNamespace(
        id="agent-1",
        workspace_id="ws-1",
        interaction_config={
            "file_upload": True,
            "file_upload_setting": {"file_upload_type": ["document"]},
        },
    )
    actor = SimpleNamespace(id="user-1")
    db = SimpleNamespace()
    upload_item = WorkflowUpload(
        id="u1",
        workspace_id="ws-1",
        agent_id="agent-1",
        uploaded_by_user_id="user-1",
        filename="notes.txt",
        content_type="text/plain",
        size_bytes=5,
        category="document",
    )

    async def run() -> None:
        with patch(
            "app.application.workflow_uploads.get_workflow_agent",
            new=AsyncMock(return_value=agent),
        ), patch(
            "app.application.workflow_uploads.require_agent_view",
            new=AsyncMock(),
        ), patch(
            "app.application.workflow_uploads._upload_files",
            new=AsyncMock(return_value=[upload_item]),
        ):
            responses = await upload_workspace_workflow_files(
                db, "ws-1", "agent-1", actor, "member",  # type: ignore[arg-type]
                [_upload_file("notes.txt")],
                SimpleNamespace(),
            )
        assert responses[0].filename == "notes.txt"

        with patch(
            "app.application.workflow_uploads.get_agent",
            new=AsyncMock(return_value=agent),
        ), patch(
            "app.application.workflow_uploads.require_agent_view",
            new=AsyncMock(),
        ), patch(
            "app.application.workflow_uploads._upload_files",
            new=AsyncMock(return_value=[upload_item]),
        ):
            responses = await upload_workspace_agent_files(
                db, "ws-1", "agent-1", actor, "member",  # type: ignore[arg-type]
                [_upload_file("notes.txt")],
                SimpleNamespace(),
            )
        assert responses[0].filename == "notes.txt"

        with patch(
            "app.application.workflow_uploads.get_workflow_agent",
            new=AsyncMock(return_value=agent),
        ), patch(
            "app.application.workflow_uploads.require_agent_view",
            new=AsyncMock(),
        ), patch(
            "app.application.workflow_uploads._resolve_workflow_files",
            new=AsyncMock(return_value=[{"id": "u1", "name": "notes.txt"}]),
        ):
            resolved = await resolve_workspace_workflow_files(
                db, "ws-1", "agent-1", actor, "member",  # type: ignore[arg-type]
                ["u1"],
                SimpleNamespace(),
                extract_text=True,
            )
        assert resolved == [{"id": "u1", "name": "notes.txt"}]

        with patch(
            "app.application.workflow_uploads.get_agent",
            new=AsyncMock(return_value=agent),
        ), patch(
            "app.application.workflow_uploads.require_agent_view",
            new=AsyncMock(),
        ), patch(
            "app.application.workflow_uploads._resolve_agent_file_text",
            new=AsyncMock(
                return_value=(
                    "--- notes.txt ---\nhello",
                    [
                        {
                            "filename": "notes.txt",
                            "content_type": "text/plain",
                            "size_bytes": 5,
                            "category": "document",
                        }
                    ],
                )
            ),
        ):
            text, attachments = await resolve_workspace_agent_files(
                db, "ws-1", "agent-1", actor, "member",  # type: ignore[arg-type]
                ["u1"],
                SimpleNamespace(),
            )
        assert text == "--- notes.txt ---\nhello"
        assert attachments[0]["filename"] == "notes.txt"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# workflow_access.py unit tests
# ---------------------------------------------------------------------------


def test_workflow_access_helpers_and_rate_limit() -> None:
    from app.application.workflow_access import _external_error, _rate_limit
    from app.infrastructure.agent_rate_limit import (
        AgentRateLimitExceeded,
        AgentRateLimitUnavailable,
    )
    from fastapi import HTTPException

    assert _external_error("failed") == "Workflow run failed."
    assert _external_error("cancelled") == "Workflow run was cancelled."
    assert _external_error("succeeded") is None

    async def run() -> None:
        with patch(
            "app.application.workflow_access.enforce_external_agent_rate_limit",
            new=AsyncMock(side_effect=AgentRateLimitExceeded(42)),
        ):
            try:
                await _rate_limit(SimpleNamespace(), "wf-1", "public", "user-1")
            except HTTPException as exc:
                assert exc.status_code == 429
                assert exc.headers == {"Retry-After": "42"}
            else:
                raise AssertionError("rate limit exceeded was not surfaced")

        with patch(
            "app.application.workflow_access.enforce_external_agent_rate_limit",
            new=AsyncMock(side_effect=AgentRateLimitUnavailable()),
        ):
            try:
                await _rate_limit(SimpleNamespace(), "wf-1", "public", "user-1")
            except HTTPException as exc:
                assert exc.status_code == 503
            else:
                raise AssertionError("rate limit unavailable was not surfaced")

    asyncio.run(run())


def test_workflow_access_external_run_branches() -> None:
    from app.application.workflow_access import (
        _external_run,
        create_external_workflow_run,
    )
    from app.entities.agents import AgentRun
    from app.entities.workflows import WorkflowRunDetail
    from app.infrastructure.repositories import workflow as workflow_repository
    from app.schemas.workflow import ExternalWorkflowRunCreateRequest
    from fastapi import HTTPException

    async def run() -> None:
        run = AgentRun(
            id="run-1",
            agent_id="wf-1",
            access_source="public",
            consumer_id="user-1",
        )
        detail = WorkflowRunDetail(run_id="run-1", inputs={"question": "q"})
        with patch(
            "app.application.workflow_access.get_published_workflow_context",
            new=AsyncMock(),
        ), patch(
            "app.application.workflow_access.agent_repository.get_agent_run_by_id",
            new=AsyncMock(return_value=run),
        ), patch(
            "app.application.workflow_access.workflow_repository.get_run_detail",
            new=AsyncMock(return_value=detail),
        ):
            loaded_run, loaded_detail = await _external_run(
                object(), "wf-1", "run-1", "public", "user-1"  # type: ignore[arg-type]
            )
        assert loaded_run.id == "run-1" and loaded_detail is detail

        # run does not belong to this consumer
        with patch(
            "app.application.workflow_access.get_published_workflow_context",
            new=AsyncMock(),
        ), patch(
            "app.application.workflow_access.agent_repository.get_agent_run_by_id",
            new=AsyncMock(return_value=run),
        ):
            try:
                await _external_run(
                    object(), "wf-1", "run-1", "public", "someone-else"  # type: ignore[arg-type]
                )
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("foreign run was accepted")

        # missing detail
        with patch(
            "app.application.workflow_access.get_published_workflow_context",
            new=AsyncMock(),
        ), patch(
            "app.application.workflow_access.agent_repository.get_agent_run_by_id",
            new=AsyncMock(return_value=run),
        ), patch(
            "app.application.workflow_access.workflow_repository.get_run_detail",
            new=AsyncMock(return_value=None),
        ):
            try:
                await _external_run(
                    object(), "wf-1", "run-1", "public", "user-1"  # type: ignore[arg-type]
                )
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("missing detail was accepted")

        # api runs cannot use public upload ids
        context = SimpleNamespace(
            agent=SimpleNamespace(id="wf-1", workspace_id="ws-1")
        )
        payload = ExternalWorkflowRunCreateRequest(
            question="q", file_ids=["u1"]
        )
        with patch(
            "app.application.workflow_access.enforce_external_agent_rate_limit",
            new=AsyncMock(),
        ):
            try:
                await create_external_workflow_run(
                    object(),  # type: ignore[arg-type]
                    context,  # type: ignore[arg-type]
                    "api",
                    "credential-1",
                    payload,
                    SimpleNamespace(),
                    SimpleNamespace(),
                )
            except HTTPException as exc:
                assert exc.status_code == 422
            else:
                raise AssertionError("api upload ids were accepted")

        # missing published version
        payload = ExternalWorkflowRunCreateRequest(question="q")
        with patch(
            "app.application.workflow_access.enforce_external_agent_rate_limit",
            new=AsyncMock(),
        ), patch.object(
            workflow_repository,
            "get_version",
            new=AsyncMock(return_value=None),
        ):
            try:
                await create_external_workflow_run(
                    object(),  # type: ignore[arg-type]
                    context,  # type: ignore[arg-type]
                    "public",
                    "user-1",
                    payload,
                    SimpleNamespace(),
                    SimpleNamespace(),
                )
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("missing version was accepted")

    asyncio.run(run())


def test_workflow_access_stream_mapping() -> None:
    from app.application.workflow_access import stream_external_workflow_run
    from datetime import UTC

    payload = {
        "id": "run-1",
        "conversation_id": "conv-1",
        "inputs": {"question": "q"},
        "outputs": {},
        "status": "succeeded",
        "created_at": datetime.now(UTC),
        "started_at": datetime.now(UTC),
        "finished_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "pending_form": None,
    }

    async def fake_stream(run_id, settings, *, after=0, live_after="0-0"):
        yield {"type": "answer_delta", "node_id": "llm-1", "delta": "hello",
               "live_sequence": "1-1", "stream_epoch": "worker-1"}
        yield {"type": "run", "sequence": 1, "run": payload}
        yield {"type": "workflow_node_started", "node_id": "llm-1",
               "node_type": "llm", "sequence": 2}
        yield {"type": "workflow_node", "node_id": "llm-1", "node_type": "llm",
               "status": "failed", "sequence": 2, "duration_ms": 12}
        yield {"type": "workflow_node", "node_id": "llm-1", "node_type": "llm",
               "status": "succeeded", "sequence": 3, "duration_ms": 4}
        yield {"type": "complete", "sequence": 4, "run": payload}

    async def run() -> None:
        with patch(
            "app.application.workflow_access.stream_workflow_run",
            new=fake_stream,
        ):
            events = [
                event
                async for event in stream_external_workflow_run(
                    "run-1", SimpleNamespace()
                )
            ]
        assert events[0] == {
            "live_sequence": "1-1",
            "stream_epoch": "worker-1",
            "type": "answer_delta",
            "node_id": "llm-1",
            "delta": "hello",
        }
        assert events[1]["type"] == "run"
        assert events[1]["run"]["id"] == "run-1"
        assert events[2] == {
            "type": "progress",
            "sequence": 2,
            "event": {
                "id": "workflow-node-llm-1",
                "node_id": "llm-1",
                "node_type": "llm",
                "status": "running",
                "error": None,
                "duration_ms": None,
            },
        }
        assert events[3]["event"]["status"] == "failed"
        assert events[3]["event"]["error"] == "Workflow node failed."
        assert events[4]["event"]["status"] == "succeeded"
        assert events[4]["event"]["error"] is None
        assert events[5]["type"] == "complete"

    asyncio.run(run())


def test_workflow_access_conversations_and_run_listing() -> None:
    from app.application.workflow_access import (
        get_external_workflow_run,
        list_public_workflow_conversations,
    )
    from app.entities.agents import AgentRun
    from app.entities.workflows import WorkflowRunDetail

    async def run() -> None:
        run = AgentRun(
            id="run-1",
            agent_id="wf-1",
            access_source="public",
            consumer_id="user-1",
            status="succeeded",
        )
        detail = WorkflowRunDetail(
            run_id="run-1", inputs={"question": "q"}, outputs={"result": "r"}
        )
        execution = SimpleNamespace(
            id="exec-1",
            node_id="llm-1",
            node_type="llm",
            status="succeeded",
            duration_ms=5,
        )
        with patch(
            "app.application.workflow_access._external_run",
            new=AsyncMock(return_value=(run, detail)),
        ), patch(
            "app.application.workflow_access.workflow_repository."
            "list_node_executions",
            new=AsyncMock(return_value=[execution]),
        ):
            response = await get_external_workflow_run(
                object(), "wf-1", "run-1", "public", "user-1"  # type: ignore[arg-type]
            )
        assert response.outputs == {"result": "r"}
        assert response.progress[0].node_id == "llm-1"
        assert response.error is None

        # conversations: rows without detail are skipped
        row = SimpleNamespace(
            run_id="run-1",
            conversation_id="conv-1",
            status="succeeded",
            run_count=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        row_without_detail = SimpleNamespace(
            run_id="run-other",
            conversation_id="conv-2",
            status="succeeded",
            run_count=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        with patch(
            "app.application.workflow_access.get_published_workflow_context",
            new=AsyncMock(),
        ), patch(
            "app.application.workflow_access.agent_repository."
            "list_consumer_conversations",
            new=AsyncMock(return_value=[row, row_without_detail]),
        ), patch(
            "app.application.workflow_access.workflow_repository."
            "list_run_details_for_external_conversations",
            new=AsyncMock(return_value=[detail]),
        ):
            response = await list_public_workflow_conversations(
                object(), "wf-1", "user-1"  # type: ignore[arg-type]
            )
        assert len(response.items) == 1
        assert response.items[0].conversation_id == "conv-1"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# executor integration tests (manual runs against the real test database)
# ---------------------------------------------------------------------------


def _simple_graph(*nodes: dict, edges: list[dict] | None = None) -> dict:
    base = [
        {
            "id": "start",
            "type": "workflow",
            "position": {"x": 0, "y": 0},
            "data": {"type": "start", "title": "Start", "config": {}},
        }
    ]
    return {
        "nodes": base + list(nodes),
        "edges": edges or [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _graph_node(node_id: str, node_type: str, config: dict) -> dict:
    return {
        "id": node_id,
        "type": "workflow",
        "position": {"x": 200, "y": 0},
        "data": {"type": node_type, "title": node_type, "config": config},
    }


def _make_running_run(graph: dict) -> str:
    from app.entities.agents import AgentRun
    from app.entities.workflows import WorkflowRunDetail
    from app.infrastructure.model_utils import utc_now
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import workflow as workflow_repository
    from app.infrastructure.session import get_session_factory
    from app.shareddomain.workflows.resources import (
        build_workflow_resource_snapshot,
        workflow_resource_hash,
    )

    async def create() -> str:
        async with get_session_factory()() as db:
            run = AgentRun(
                workspace_id=WORKSPACE_ID,
                agent_id=WORKFLOW_AGENT_ID,
                requested_by_user_id=ADMIN_USER_ID,
                execution_user_id=ADMIN_USER_ID,
                access_source="console",
                consumer_id=ADMIN_USER_ID,
                goal="manual",
                model_id=WORKFLOW_MODEL_ID,
                model_name="test",
                status="running",
                worker_task_id="worker-manual",
                lease_expires_at=utc_now() + timedelta(seconds=300),
                checkpoint_phase="workflow",
                trace_id="trace-manual",
                model_usage={},
            )
            run = await agent_repository.create_agent_run(db, run)
            resource_snapshot = build_workflow_resource_snapshot([], [])
            detail = WorkflowRunDetail(
                workspace_id=WORKSPACE_ID,
                definition_id=WORKFLOW_DEFINITION_ID,
                run_id=run.id,
                graph_snapshot=graph,
                resource_snapshot=resource_snapshot,
                resource_hash=workflow_resource_hash(resource_snapshot),
                inputs={"question": "manual"},
                max_steps=20,
                max_model_tokens=10000,
                deadline_at=utc_now() + timedelta(seconds=60),
            )
            await workflow_repository.create_run_detail(db, detail)
            await db.commit()
            return run.id

    return asyncio.run(create())


def _execute_claimed(run_id: str, *, lease_lost: bool = False) -> str:
    from app.application.workflow_executor import _execute_claimed_workflow_run

    async def run() -> str:
        event = asyncio.Event()
        if lease_lost:
            event.set()
        try:
            await _execute_claimed_workflow_run(
                run_id,
                "worker-manual",
                tests.support.settings(),
                event,
            )
        except WorkflowEngineError as exc:
            return f"ERROR: {exc}"
        return "OK"

    return asyncio.run(run())


def test_executor_manual_run_scenarios() -> None:
    """Executor error paths exercised with real DB rows and targeted mocks."""
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import workflow as workflow_repository
    from tests.agents import agent_model_server, create_workspace_user, model_payload

    global WORKSPACE_ID, WORKFLOW_AGENT_ID, ADMIN_USER_ID, WORKFLOW_MODEL_ID
    global WORKFLOW_DEFINITION_ID

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id = activate_admin(client)
        WORKSPACE_ID = workspace_id
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_base_url, "Workflow Model"),
        )
        assert model.status_code == 201, model.text
        WORKFLOW_MODEL_ID = model.json()["id"]
        workflow = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=headers,
            json={
                "name": "Manual Workflow",
                "app_type": "workflow",
                "model_id": WORKFLOW_MODEL_ID,
            },
        )
        assert workflow.status_code == 201, workflow.text
        WORKFLOW_AGENT_ID = workflow.json()["id"]
        ADMIN_USER_ID = client.get("/api/v1/auth/me", headers=headers).json()[
            "user"
        ]["id"]
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{WORKFLOW_AGENT_ID}"
        definition = client.get(f"{base}/definition", headers=headers)
        assert definition.status_code == 200, definition.text
        WORKFLOW_DEFINITION_ID = definition.json()["id"]

        # lease-lost before execution
        graph = _simple_graph(
            _graph_node("end", "end", {"outputs": {"result": "done"}}),
            edges=[{"id": "e1", "source": "start", "target": "end"}],
        )
        run_id = _make_running_run(graph)
        outcome = _execute_claimed(run_id, lease_lost=True)
        assert "ERROR: Workflow run lease was lost." in outcome, outcome

        # on_started cannot persist the execution row
        run_id = _make_running_run(graph)
        with patch.object(
            workflow_repository,
            "start_node_execution",
            new=AsyncMock(return_value=None),
        ):
            outcome = _execute_claimed(run_id)
        assert "ERROR: Workflow run lease was lost." in outcome, outcome

        # on_started cannot persist the event
        run_id = _make_running_run(graph)
        with patch.object(
            agent_repository,
            "append_owned_agent_run_event",
            new=AsyncMock(return_value=None),
        ):
            outcome = _execute_claimed(run_id)
        assert "ERROR: Workflow run lease was lost." in outcome, outcome

        # finish_node_execution fails -> lease lost during on_finished
        run_id = _make_running_run(graph)
        with patch.object(
            workflow_repository,
            "finish_node_execution",
            new=AsyncMock(return_value=False),
        ):
            outcome = _execute_claimed(run_id)
        assert "ERROR: Workflow run lease was lost." in outcome, outcome

        # a skipped branch whose fallback execution row cannot be created
        condition_graph = _simple_graph(
            _graph_node(
                "condition",
                "condition",
                {
                    "branch": [
                        {
                            "id": "yes_branch",
                            "type": "IF",
                            "condition": "and",
                            "conditions": [
                                {
                                    "field": ["start", "question"],
                                    "compare": "eq",
                                    "value": "manual",
                                }
                            ],
                        },
                        {"id": "no_branch", "type": "ELSE", "condition": "and", "conditions": []},
                    ]
                },
            ),
            _graph_node("yes", "variable", {"value": "yes"}),
            _graph_node("no", "variable", {"value": "no"}),
            _graph_node("end", "end", {"outputs": {"result": "{{yes.value}}"}}),
            edges=[
                {"id": "e1", "source": "start", "target": "condition"},
                {"id": "e2", "source": "condition", "sourceHandle": "yes_branch", "target": "yes"},
                {"id": "e3", "source": "condition", "sourceHandle": "no_branch", "target": "no"},
                {"id": "e4", "source": "yes", "target": "end"},
                {"id": "e5", "source": "no", "target": "end"},
            ],
        )
        run_id = _make_running_run(condition_graph)
        real_start = workflow_repository.start_node_execution

        async def fake_start(db, *, node_id, **kwargs):
            if node_id == "no":
                return None
            return await real_start(db, node_id=node_id, **kwargs)

        with patch.object(
            workflow_repository,
            "start_node_execution",
            new=fake_start,
        ):
            outcome = _execute_claimed(run_id)
        assert "ERROR: Workflow run lease was lost." in outcome, outcome

        # a successful condition run covers the skipped-node fallback path
        run_id = _make_running_run(condition_graph)
        outcome = _execute_claimed(run_id)
        assert outcome == "OK", outcome
        async def check_success() -> None:
            from app.infrastructure.session import get_session_factory

            async with get_session_factory()() as db:
                nodes = await workflow_repository.list_node_executions(db, run_id)
            assert {item.node_id for item in nodes} == {
                "start",
                "condition",
                "yes",
                "no",
                "end",
            }
        asyncio.run(check_success())

        # node output exceeds the 256 KiB budget
        from app.application.workflow_executor import execute_workflow_node as real_execute
        from app.shareddomain.workflows.engine import NodeResult

        async def huge_node(scope, node, context):
            return NodeResult(outputs={"text": "x" * (300 * 1024)})

        run_id = _make_running_run(graph)
        with patch(
            "app.application.workflow_executor.execute_workflow_node",
            new=huge_node,
        ):
            outcome = _execute_claimed(run_id)
        assert "exceeds 256 KiB" in outcome, outcome

        # final merged output exceeds the budget while each node fits
        big_graph = _simple_graph(
            _graph_node("llm-1", "llm", {"prompt": "p"}),
            _graph_node("llm-2", "llm", {"prompt": "p"}),
            _graph_node("end", "end", {"outputs": {}}),
            edges=[
                {"id": "e1", "source": "start", "target": "llm-1"},
                {"id": "e2", "source": "llm-1", "target": "llm-2"},
                {"id": "e3", "source": "llm-2", "target": "end"},
            ],
        )

        async def big_nodes(scope, node, context):
            if node.data.type == "end":
                return NodeResult(outputs={})
            return NodeResult(outputs={"text": "y" * (200 * 1024)})

        run_id = _make_running_run(big_graph)
        with patch(
            "app.application.workflow_executor.execute_workflow_node",
            new=big_nodes,
        ):
            outcome = _execute_claimed(run_id)
        assert "exceeds 256 KiB" in outcome, outcome

        # checkpoint with form submissions: a non-form node finishing while
        # submissions remain persists them into the checkpoint payload
        from app.entities.agents import AgentRun as AgentRunEntity
        from app.entities.workflows import WorkflowRunDetail as RunDetailEntity

        checkpoint_graph = _simple_graph(
            _graph_node("v", "variable", {"value": "{{start.question}}"}),
            _graph_node("end", "end", {"outputs": {"result": "{{v.value}}"}}),
            edges=[
                {"id": "e1", "source": "start", "target": "v"},
                {"id": "e2", "source": "v", "target": "end"},
            ],
        )
        checkpoint = {
            "workflow_engine": {
                "node_states": {"start": "succeeded", "v": "pending", "end": "pending"},
                "edge_states": {"e1": "taken", "e2": "unknown"},
                "node_outputs": {"start": {"question": "cp", "files": []}},
                "step_count": 1,
                "model_tokens": 0,
            },
            "workflow_form_submissions": {"form-x": {"email": "user@example.com"}},
        }

        async def create_checkpoint_run() -> str:
            from app.infrastructure.model_utils import utc_now
            from app.infrastructure.repositories import agent as agent_repository
            from app.infrastructure.repositories import workflow as workflow_repository
            from app.infrastructure.session import get_session_factory
            from app.shareddomain.workflows.resources import (
                build_workflow_resource_snapshot,
                workflow_resource_hash,
            )

            async with get_session_factory()() as db:
                run = AgentRunEntity(
                    workspace_id=WORKSPACE_ID,
                    agent_id=WORKFLOW_AGENT_ID,
                    requested_by_user_id=ADMIN_USER_ID,
                    execution_user_id=ADMIN_USER_ID,
                    access_source="console",
                    consumer_id=ADMIN_USER_ID,
                    goal="cp",
                    model_id=WORKFLOW_MODEL_ID,
                    model_name="test",
                    status="running",
                    worker_task_id="worker-manual",
                    lease_expires_at=utc_now() + timedelta(seconds=300),
                    checkpoint=checkpoint,
                    checkpoint_phase="workflow",
                    trace_id="trace-cp",
                    model_usage={},
                )
                run = await agent_repository.create_agent_run(db, run)
                resource_snapshot = build_workflow_resource_snapshot([], [])
                detail = RunDetailEntity(
                    workspace_id=WORKSPACE_ID,
                    definition_id=WORKFLOW_DEFINITION_ID,
                    run_id=run.id,
                    graph_snapshot=checkpoint_graph,
                    resource_snapshot=resource_snapshot,
                    resource_hash=workflow_resource_hash(resource_snapshot),
                    inputs={"question": "cp"},
                    max_steps=20,
                    max_model_tokens=10000,
                    deadline_at=utc_now() + timedelta(seconds=60),
                )
                await workflow_repository.create_run_detail(db, detail)
                await db.commit()
                return run.id

        checkpoint_run_id = asyncio.run(create_checkpoint_run())
        outcome = _execute_claimed(checkpoint_run_id)
        assert outcome == "OK", outcome

        # finalized run whose completion state cannot be re-read
        def finalized_missing() -> None:
            run_id = _make_running_run(graph)
            real_get_run = agent_repository.get_agent_run_by_id

            async def fake_get_run(db, looked_up_run_id):
                run = await real_get_run(db, looked_up_run_id)
                if run is not None and run.status == "succeeded":
                    return None
                return run

            with patch.object(
                agent_repository,
                "get_agent_run_by_id",
                new=fake_get_run,
            ):
                outcome = _execute_claimed(run_id)
            assert "Finalized workflow run state is missing." in outcome, outcome

        finalized_missing()

        # _fail_claimed_workflow_run with a missing run
        from app.application.workflow_executor import _fail_claimed_workflow_run

        async def fail_missing() -> str:
            return await _fail_claimed_workflow_run(
                "missing-run", "worker-x", ValueError("boom")
            )

        assert asyncio.run(fail_missing()) == "finished"

        # run_durable_workflow_run: claim held by another worker
        from app.entities.agents import AgentRun
        from app.infrastructure.model_utils import utc_now
        from app.infrastructure.session import get_session_factory
        from app.application.workflow_executor import run_durable_workflow_run

        async def busy_claim() -> str:
            async with get_session_factory()() as db:
                held = AgentRun(
                    workspace_id=WORKSPACE_ID,
                    agent_id=WORKFLOW_AGENT_ID,
                    requested_by_user_id=ADMIN_USER_ID,
                    execution_user_id=ADMIN_USER_ID,
                    access_source="console",
                    consumer_id=ADMIN_USER_ID,
                    status="running",
                    worker_task_id="other-worker",
                    lease_expires_at=utc_now() + timedelta(seconds=3600),
                    checkpoint_phase="workflow",
                    model_usage={},
                )
                held = await agent_repository.create_agent_run(db, held)
                await db.commit()
                held_id = held.id
            outcome = await run_durable_workflow_run(
                held_id, tests.support.settings(), worker_task_id="worker-x"
            )
            assert outcome == "busy", outcome
            async with get_session_factory()() as db:
                held.status = "failed"
                await agent_repository.save_agent_run(db, held)
                await db.commit()
            outcome = await run_durable_workflow_run(
                held_id, tests.support.settings(), worker_task_id="worker-x"
            )
            assert outcome == "finished", outcome
            return "OK"

        assert asyncio.run(busy_claim()) == "OK"


# ---------------------------------------------------------------------------
# end-to-end API test: public + api workflow access and executor flows
# ---------------------------------------------------------------------------


def _publish_graph(
    client,
    headers: dict,
    base: str,
    graph: dict,
    revision: int,
) -> int:
    saved = client.put(
        f"{base}/definition",
        headers=headers,
        json={"expected_revision": revision, "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    published = client.post(f"{base}/publish", headers=headers)
    assert published.status_code == 201, published.text
    return saved.json()["revision"]


def test_public_and_api_workflow_access_end_to_end() -> None:
    from tests.agents import agent_model_server, create_workspace_user, model_payload

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_base_url, "Workflow Model"),
        )
        assert model.status_code == 201, model.text
        model_id = model.json()["id"]
        workflow = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=headers,
            json={
                "name": "Public Workflow",
                "app_type": "workflow",
                "model_id": model_id,
                "interaction_config": {
                    "prologue": "Choose inputs to start.",
                    "tts_type": "BROWSER",
                    "file_upload": True,
                    "file_upload_setting": {
                        "file_upload_type": ["document"],
                    },
                    "user_input_title": "Release options",
                },
            },
        )
        assert workflow.status_code == 201, workflow.text
        workflow_id = workflow.json()["id"]
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{workflow_id}"

        revision = 1
        value_graph = _simple_graph(
            _graph_node("value", "variable", {"value": "{{start.question}}"}),
            _graph_node("end", "end", {"outputs": {"result": "{{value.value}}"}}),
            edges=[
                {"id": "e1", "source": "start", "target": "value"},
                {"id": "e2", "source": "value", "target": "end"},
            ],
        )
        revision = _publish_graph(client, headers, base, value_graph, revision)

        member_id, temporary_password = create_workspace_user(
            client, token, workspace_id
        )
        member_token = activate_user(
            client,
            "agent-member",
            temporary_password,
            "WorkflowMember@123!",
        )
        member_headers = auth_headers(member_token)
        grant = client.put(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}/permissions/{member_id}",
            headers=headers,
            json={"permission": "view"},
        )
        assert grant.status_code == 200, grant.text

        # public profile
        profile = client.get(
            f"/api/v1/public/workflows/{workflow_id}/profile",
            headers=member_headers,
        )
        assert profile.status_code == 200, profile.text
        assert profile.json()["interaction_config"]["file_upload"] is True

        # public conversations (empty)
        conversations = client.get(
            f"/api/v1/public/workflows/{workflow_id}/conversations",
            headers=member_headers,
        )
        assert conversations.status_code == 200, conversations.text
        assert conversations.json()["items"] == []

        # public uploads: happy path
        uploaded = client.post(
            f"/api/v1/public/workflows/{workflow_id}/uploads",
            headers=member_headers,
            files={"files": ("notes.txt", b"release notes", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
        upload_id = uploaded.json()[0]["id"]

        # public uploads: disabled uploads -> 409
        disabled_config = client.patch(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}",
            headers=headers,
            json={
                "interaction_config": {
                    "prologue": "Choose inputs to start.",
                    "tts_type": "BROWSER",
                    "file_upload": False,
                    "user_input_title": "Release options",
                }
            },
        )
        assert disabled_config.status_code == 200, disabled_config.text
        revision = _publish_graph(client, headers, base, value_graph, revision)
        disabled_upload = client.post(
            f"/api/v1/public/workflows/{workflow_id}/uploads",
            headers=member_headers,
            files={"files": ("notes.txt", b"release notes", "text/plain")},
        )
        assert disabled_upload.status_code == 409, disabled_upload.text

        # restore document uploads and publish
        enabled_config = client.patch(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}",
            headers=headers,
            json={
                "interaction_config": {
                    "prologue": "Choose inputs to start.",
                    "tts_type": "BROWSER",
                    "file_upload": True,
                    "file_upload_setting": {
                        "file_upload_type": ["document"],
                    },
                    "user_input_title": "Release options",
                }
            },
        )
        assert enabled_config.status_code == 200, enabled_config.text
        revision = _publish_graph(client, headers, base, value_graph, revision)

        # public uploads: unsupported type -> 422
        bad_upload = client.post(
            f"/api/v1/public/workflows/{workflow_id}/uploads",
            headers=member_headers,
            files={"files": ("evil.exe", b"MZ", "application/octet-stream")},
        )
        assert bad_upload.status_code == 422, bad_upload.text

        # public run (graph A)
        public_run = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs",
            headers=member_headers,
            json={"question": "public-workflow"},
        )
        assert public_run.status_code == 201, public_run.text
        assert public_run.json()["status"] == "succeeded"
        assert public_run.json()["outputs"] == {"result": "public-workflow"}
        public_run_id = public_run.json()["id"]

        # public run listing
        public_runs = client.get(
            f"/api/v1/public/workflows/{workflow_id}/runs",
            headers=member_headers,
        )
        assert public_runs.status_code == 200, public_runs.text
        assert public_runs.json()["total"] == 1
        assert public_runs.json()["items"][0]["id"] == public_run_id

        # public run detail + 404 for a foreign/missing run
        public_detail = client.get(
            f"/api/v1/public/workflows/{workflow_id}/runs/{public_run_id}",
            headers=member_headers,
        )
        assert public_detail.status_code == 200, public_detail.text
        assert public_detail.json()["outputs"] == {"result": "public-workflow"}
        missing_detail = client.get(
            f"/api/v1/public/workflows/{workflow_id}/runs/missing-run",
            headers=member_headers,
        )
        assert missing_detail.status_code == 404, missing_detail.text

        # public stream replays durable events
        public_stream = client.get(
            f"/api/v1/public/workflows/{workflow_id}/runs/{public_run_id}/stream",
            headers=member_headers,
        )
        assert public_stream.status_code == 200, public_stream.text
        stream_types = [
            json.loads(line)["type"] for line in public_stream.text.splitlines()
        ]
        assert stream_types[0] == "run"
        assert stream_types[-1] == "complete"
        assert "progress" in stream_types

        # conversations now include the finished run
        conversations = client.get(
            f"/api/v1/public/workflows/{workflow_id}/conversations",
            headers=member_headers,
        )
        assert conversations.status_code == 200, conversations.text
        assert conversations.json()["items"][0]["outputs"] == {
            "result": "public-workflow"
        }

        # api credential flows against graph A
        credential = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}/api-credentials",
            headers=headers,
            json={"name": "Integration"},
        )
        assert credential.status_code == 201, credential.text
        api_headers = {"Authorization": f"Bearer {credential.json()['token']}"}

        # missing/invalid API credentials -> 401
        unauthorized = client.get(
            f"/api/v1/workflow-api/{workflow_id}/documentation",
        )
        assert unauthorized.status_code == 401, unauthorized.text
        bad_scheme = client.get(
            f"/api/v1/workflow-api/{workflow_id}/documentation",
            headers={"Authorization": "Basic abc"},
        )
        assert bad_scheme.status_code == 401, bad_scheme.text

        documentation = client.get(
            f"/api/v1/workflow-api/{workflow_id}/documentation",
            headers=api_headers,
        )
        assert documentation.status_code == 200, documentation.text
        assert documentation.json()["workflow_id"] == workflow_id

        api_run = client.post(
            f"/api/v1/workflow-api/{workflow_id}/runs",
            headers=api_headers,
            json={"question": "api-workflow"},
        )
        assert api_run.status_code == 201, api_run.text
        assert api_run.json()["status"] == "succeeded"
        api_run_id = api_run.json()["id"]

        # api runs cannot use public upload ids
        api_file_run = client.post(
            f"/api/v1/workflow-api/{workflow_id}/runs",
            headers=api_headers,
            json={"question": "api-file", "file_ids": [upload_id]},
        )
        assert api_file_run.status_code == 422, api_file_run.text

        api_detail = client.get(
            f"/api/v1/workflow-api/{workflow_id}/runs/{api_run_id}",
            headers=api_headers,
        )
        assert api_detail.status_code == 200, api_detail.text
        assert api_detail.json()["outputs"] == {"result": "api-workflow"}

        api_stream = client.get(
            f"/api/v1/workflow-api/{workflow_id}/runs/{api_run_id}/stream",
            headers=api_headers,
        )
        assert api_stream.status_code == 200, api_stream.text
        assert json.loads(api_stream.text.splitlines()[-1])["type"] == "complete"

        # workspace upload endpoint (upload_workspace_workflow_files)
        workspace_upload = client.post(
            f"{base}/uploads",
            headers=headers,
            files={"files": ("workspace.txt", b"workspace file", "text/plain")},
        )
        assert workspace_upload.status_code == 201, workspace_upload.text
        workspace_upload_id = workspace_upload.json()[0]["id"]

        # console run with file_ids (resolve_workspace_workflow_files)
        console_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={
                "source": "draft",
                "question": "console-file",
                "file_ids": [workspace_upload_id],
            },
        )
        assert console_run.status_code == 201, console_run.text
        assert console_run.json()["status"] == "succeeded"

        # document-extract graph with public upload (extract_text path)
        document_graph = _simple_graph(
            _graph_node(
                "document",
                "document-extract-node",
                {"document_list": "{{start.files}}"},
            ),
            _graph_node("end", "end", {"outputs": {"result": "{{document.content}}"}}),
            edges=[
                {"id": "e1", "source": "start", "target": "document"},
                {"id": "e2", "source": "document", "target": "end"},
            ],
        )
        revision = _publish_graph(client, headers, base, document_graph, revision)
        file_run = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs",
            headers=member_headers,
            json={"question": "with-file", "file_ids": [upload_id]},
        )
        assert file_run.status_code == 201, file_run.text
        assert file_run.json()["status"] == "succeeded"
        assert "release notes" in file_run.json()["outputs"]["result"]

        # llm graph (output_delta path)
        llm_graph = _simple_graph(
            _graph_node("llm", "llm", {"prompt": "say hello", "model_id": model_id}),
            _graph_node("end", "end", {"outputs": {}}),
            edges=[
                {"id": "e1", "source": "start", "target": "llm"},
                {"id": "e2", "source": "llm", "target": "end"},
            ],
        )
        revision = _publish_graph(client, headers, base, llm_graph, revision)
        llm_run = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs",
            headers=member_headers,
            json={"question": "llm-question"},
        )
        assert llm_run.status_code == 201, llm_run.text
        assert llm_run.json()["status"] == "succeeded"
        assert llm_run.json()["outputs"]["result"] == "Completed."

        # form graph: pause, stream, public form submit
        form_graph = _simple_graph(
            _graph_node(
                "form",
                "form-node",
                {
                    "form_field_list": [
                        {
                            "variable": "email",
                            "name": "Email",
                            "type": "input",
                            "is_required": True,
                        }
                    ],
                    "form_content_format": "Please submit {{ form }}",
                },
            ),
            _graph_node("end", "end", {"outputs": {"result": "{{form.email}}"}}),
            edges=[
                {"id": "e1", "source": "start", "target": "form"},
                {"id": "e2", "source": "form", "target": "end"},
            ],
        )
        revision = _publish_graph(client, headers, base, form_graph, revision)
        form_run = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs",
            headers=member_headers,
            json={"question": "form-question"},
        )
        assert form_run.status_code == 201, form_run.text
        assert form_run.json()["status"] == "awaiting_input"
        form_run_id = form_run.json()["id"]
        form_detail = client.get(
            f"/api/v1/public/workflows/{workflow_id}/runs/{form_run_id}",
            headers=member_headers,
        )
        assert form_detail.status_code == 200, form_detail.text
        assert form_detail.json()["pending_form"]["runtime_node_id"] == "form"
        assert form_detail.json()["pending_form"]["fields"][0]["variable"] == "email"

        paused_stream = client.get(
            f"/api/v1/public/workflows/{workflow_id}/runs/{form_run_id}/stream",
            headers=member_headers,
        )
        assert paused_stream.status_code == 200, paused_stream.text
        paused_types = [
            json.loads(line)["type"] for line in paused_stream.text.splitlines()
        ]
        assert paused_types[-1] == "workflow_input_required"

        form_submit = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs/{form_run_id}/form",
            headers=member_headers,
            json={
                "runtime_node_id": "form",
                "form_data": {"email": "user@example.com"},
            },
        )
        assert form_submit.status_code == 200, form_submit.text
        assert form_submit.json()["status"] == "succeeded"
        assert form_submit.json()["outputs"] == {"result": "user@example.com"}

        # api form submit
        api_form_run = client.post(
            f"/api/v1/workflow-api/{workflow_id}/runs",
            headers=api_headers,
            json={"question": "api-form"},
        )
        assert api_form_run.status_code == 201, api_form_run.text
        assert api_form_run.json()["status"] == "awaiting_input"
        api_form_submit = client.post(
            f"/api/v1/workflow-api/{workflow_id}/runs/{api_form_run.json()['id']}/form",
            headers=api_headers,
            json={
                "runtime_node_id": "form",
                "form_data": {"email": "api@example.com"},
            },
        )
        assert api_form_submit.status_code == 200, api_form_submit.text
        assert api_form_submit.json()["status"] == "succeeded"

        # failed run: node output over budget -> error response surfaces message
        huge_graph = _simple_graph(
            _graph_node("huge", "variable", {"value": "x" * (300 * 1024)}),
            _graph_node("end", "end", {"outputs": {"result": "{{huge.value}}"}}),
            edges=[
                {"id": "e1", "source": "start", "target": "huge"},
                {"id": "e2", "source": "huge", "target": "end"},
            ],
        )
        revision = _publish_graph(client, headers, base, huge_graph, revision)
        failed_run = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs",
            headers=member_headers,
            json={"question": "too-big"},
        )
        assert failed_run.status_code == 201, failed_run.text
        assert failed_run.json()["status"] == "failed"
        failed_detail = client.get(
            f"/api/v1/public/workflows/{workflow_id}/runs/{failed_run.json()['id']}",
            headers=member_headers,
        )
        assert failed_detail.status_code == 200, failed_detail.text
        assert failed_detail.json()["error"] == "Workflow run failed."

        # expired upload cleanup flow
        from app.infrastructure.model_utils import utc_now
        from app.infrastructure.object_storage import create_object_storage
        from app.infrastructure.repositories import workflow as workflow_repository
        from app.infrastructure.session import get_session_factory
        from app.shareddomain.workflows.models import WorkflowUpload
        from app.shareddomain.workflows.uploads import (
            prepare_due_upload_cleanups,
            run_upload_storage_cleanup,
        )

        expired_upload = client.post(
            f"/api/v1/public/workflows/{workflow_id}/uploads",
            headers=member_headers,
            files={"files": ("expired.txt", b"expiring", "text/plain")},
        )
        assert expired_upload.status_code == 201, expired_upload.text
        expired_id = expired_upload.json()[0]["id"]

        async def expire_and_clean() -> None:
            async with get_session_factory()() as db:
                row = await db.get(WorkflowUpload, expired_id)
                assert row is not None
                object_path = create_object_storage(
                    tests.support.settings().knowledge_storage_dir
                ).path(row.object_key)
                row.expires_at = utc_now() - timedelta(seconds=1)
                await db.commit()
            assert object_path.exists()
            cleanup_ids = await prepare_due_upload_cleanups()
            assert any(
                True for _ in cleanup_ids
            ), "expired upload was not queued for cleanup"
            for cleanup_id in cleanup_ids:
                await run_upload_storage_cleanup(
                    cleanup_id, tests.support.settings()
                )
            assert not object_path.exists()

        asyncio.run(expire_and_clean())


# ---------------------------------------------------------------------------
# direct endpoint/application calls (main-thread tracing)
# ---------------------------------------------------------------------------


def test_api_endpoint_functions_direct() -> None:
    """Call the public/api endpoint functions directly with mocked deps."""
    from app.api.v1.endpoints import workflow_access as endpoints

    async def run() -> None:
        db = SimpleNamespace(rollback=AsyncMock())
        user = SimpleNamespace(id="user-1")
        settings = SimpleNamespace()
        context = SimpleNamespace(
            agent=SimpleNamespace(id="wf-1"),
            publisher=SimpleNamespace(id="user-1"),
        )
        credential = SimpleNamespace(id="credential-1")

        async def empty_stream(run_id, settings, *, after=0, live_after="0-0"):
            return
            yield  # pragma: no cover

        with patch(
            "app.api.v1.endpoints.workflow_access."
            "get_workspace_published_workflow_context",
            new=AsyncMock(return_value=context),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "list_public_workflow_conversations",
            new=AsyncMock(return_value=SimpleNamespace(items=[])),
        ):
            await endpoints.public_workflow_conversations("wf-1", db, user)

        with patch(
            "app.api.v1.endpoints.workflow_access."
            "get_workspace_published_workflow_context",
            new=AsyncMock(return_value=context),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "list_external_workflow_runs",
            new=AsyncMock(return_value=SimpleNamespace(items=[], total=0, offset=0, limit=50)),
        ):
            await endpoints.list_public_workflow_runs("wf-1", db, user)

        with patch(
            "app.api.v1.endpoints.workflow_access."
            "get_workspace_published_workflow_context",
            new=AsyncMock(return_value=context),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "create_external_workflow_run",
            new=AsyncMock(return_value=SimpleNamespace(id="run-1")),
        ):
            result = await endpoints.create_public_workflow_run(
                "wf-1", SimpleNamespace(question="q"), settings, db, user
            )
            assert result.id == "run-1"

        with patch(
            "app.api.v1.endpoints.workflow_access."
            "get_workspace_published_workflow_context",
            new=AsyncMock(return_value=context),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "get_external_workflow_run",
            new=AsyncMock(return_value=SimpleNamespace(id="run-1")),
        ):
            await endpoints.get_public_workflow_run("wf-1", "run-1", db, user)

        with patch(
            "app.api.v1.endpoints.workflow_access."
            "get_workspace_published_workflow_context",
            new=AsyncMock(return_value=context),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "submit_external_workflow_form",
            new=AsyncMock(return_value=SimpleNamespace(id="run-1")),
        ):
            await endpoints.submit_public_workflow_form(
                "wf-1", "run-1", SimpleNamespace(runtime_node_id="form", form_data={}),
                settings, db, user,
            )

        with patch(
            "app.api.v1.endpoints.workflow_access."
            "get_workspace_published_workflow_context",
            new=AsyncMock(return_value=context),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "get_external_workflow_run",
            new=AsyncMock(return_value=SimpleNamespace(id="run-1")),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "stream_external_workflow_run",
            new=empty_stream,
        ):
            response = await endpoints.stream_public_workflow_run(
                "wf-1", "run-1", settings, db, user
            )
            assert response.status_code == 200
            assert db.rollback.await_count >= 1

        with patch(
            "app.api.v1.endpoints.workflow_access._api_context",
            new=AsyncMock(return_value=(context, credential)),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "get_workflow_api_documentation",
            new=AsyncMock(return_value=SimpleNamespace(workflow_id="wf-1")),
        ):
            result = await endpoints.get_api_workflow_documentation("wf-1", db, None)
            assert result.workflow_id == "wf-1"

        with patch(
            "app.api.v1.endpoints.workflow_access._api_context",
            new=AsyncMock(return_value=(context, credential)),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "create_external_workflow_run",
            new=AsyncMock(return_value=SimpleNamespace(id="run-1")),
        ):
            await endpoints.create_api_workflow_run(
                "wf-1", SimpleNamespace(question="q"), settings, db, None
            )

        with patch(
            "app.api.v1.endpoints.workflow_access._api_context",
            new=AsyncMock(return_value=(context, credential)),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "get_external_workflow_run",
            new=AsyncMock(return_value=SimpleNamespace(id="run-1")),
        ):
            await endpoints.get_api_workflow_run("wf-1", "run-1", db, None)

        with patch(
            "app.api.v1.endpoints.workflow_access._api_context",
            new=AsyncMock(return_value=(context, credential)),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "submit_external_workflow_form",
            new=AsyncMock(return_value=SimpleNamespace(id="run-1")),
        ):
            await endpoints.submit_api_workflow_form(
                "wf-1", "run-1", SimpleNamespace(runtime_node_id="form", form_data={}),
                settings, db, None,
            )

        with patch(
            "app.api.v1.endpoints.workflow_access._api_context",
            new=AsyncMock(return_value=(context, credential)),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "get_external_workflow_run",
            new=AsyncMock(return_value=SimpleNamespace(id="run-1")),
        ), patch(
            "app.api.v1.endpoints.workflow_access."
            "stream_external_workflow_run",
            new=empty_stream,
        ):
            response = await endpoints.stream_api_workflow_run(
                "wf-1", "run-1", settings, db, None
            )
            assert response.status_code == 200

    asyncio.run(run())


def test_workflow_access_application_functions_direct() -> None:
    """Call application-layer workflow access functions in the main thread."""
    from app.application import workflow_access as access_module
    from app.application.workflow_access import (
        create_external_workflow_run,
        get_public_workflow_profile,
        list_external_workflow_runs,
        submit_external_workflow_form,
    )
    from app.entities.agents import AgentRun
    from app.entities.workflows import WorkflowRunDetail
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import workflow as workflow_repository
    from app.schemas.workflow import ExternalWorkflowRunCreateRequest

    async def run() -> None:
        context = SimpleNamespace(
            agent=SimpleNamespace(
                id="wf-1",
                workspace_id="ws-1",
                name="WF",
                description="d",
                interaction_config={
                    "file_upload": True,
                    "file_upload_setting": {"file_upload_type": ["document"]},
                },
            ),
            workspace=SimpleNamespace(membership_role="member"),
            publication=None,
        )
        with patch(
            "app.application.workflow_access."
            "get_workspace_published_workflow_context",
            new=AsyncMock(return_value=context),
        ):
            profile = await get_public_workflow_profile(
                object(), "wf-1", SimpleNamespace()  # type: ignore[arg-type]
            )
        assert profile.id == "wf-1"
        assert profile.name == "WF"

        payload = ExternalWorkflowRunCreateRequest(question="q")
        graph = {
            "nodes": [
                {
                    "id": "start",
                    "type": "workflow",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "start", "title": "Start", "config": {}},
                }
            ],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }
        version = SimpleNamespace(graph=graph, version_number=1)
        run = SimpleNamespace(
            id="run-1",
            conversation_id="conv-1",
            inputs={"question": "q"},
            outputs={},
            status="queued",
            created_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
            updated_at=datetime.now(UTC),
        )
        with patch(
            "app.application.workflow_access.enforce_external_agent_rate_limit",
            new=AsyncMock(),
        ), patch.object(
            workflow_repository,
            "get_version",
            new=AsyncMock(return_value=version),
        ), patch(
            "app.application.workflow_access.resolve_public_workflow_files",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.application.workflow_access.create_workflow_run",
            new=AsyncMock(return_value=run),
        ):
            response = await create_external_workflow_run(
                object(),  # type: ignore[arg-type]
                context,  # type: ignore[arg-type]
                "public",
                "user-1",
                payload,
                SimpleNamespace(),
                SimpleNamespace(),
            )
        assert response.id == "run-1"
        assert response.conversation_id == "conv-1"
        assert response.status == "queued"

        # submit_external_workflow_form
        agent_run = AgentRun(id="run-1", agent_id="wf-1", status="awaiting_input")
        detail = WorkflowRunDetail(run_id="run-1")
        payload_dict = {
            "id": "run-1",
            "conversation_id": "conv-1",
            "inputs": {"question": "q"},
            "outputs": {"result": "ok"},
            "status": "succeeded",
            "created_at": datetime.now(UTC),
            "started_at": datetime.now(UTC),
            "finished_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "pending_form": None,
        }
        with patch(
            "app.application.workflow_access._external_run",
            new=AsyncMock(return_value=(agent_run, detail)),
        ), patch(
            "app.application.workflow_access.resume_workflow_form",
            new=AsyncMock(
                return_value=SimpleNamespace(model_dump=lambda mode: payload_dict)
            ),
        ):
            response = await submit_external_workflow_form(
                object(), "wf-1", "run-1", "public", "user-1",  # type: ignore[arg-type]
                SimpleNamespace(runtime_node_id="form", form_data={}),
                SimpleNamespace(),
            )
        assert response.status == "succeeded"

        # list_external_workflow_runs
        runs = [AgentRun(id="run-1", agent_id="wf-1", status="succeeded")]
        details = [WorkflowRunDetail(run_id="run-1", inputs={"question": "q"})]
        with patch(
            "app.application.workflow_access.get_published_workflow_context",
            new=AsyncMock(),
        ), patch.object(
            agent_repository,
            "list_agent_runs",
            new=AsyncMock(return_value=runs),
        ), patch.object(
            agent_repository,
            "count_agent_runs",
            new=AsyncMock(return_value=1),
        ), patch.object(
            workflow_repository,
            "list_run_details_for_external_conversations",
            new=AsyncMock(return_value=details),
        ):
            listing = await list_external_workflow_runs(
                object(), "wf-1", "public", "user-1", 10, 0  # type: ignore[arg-type]
            )
        assert listing.total == 1
        assert listing.items[0].id == "run-1"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    test_nodes_resolve_value_and_templates()
    test_nodes_reranker_candidates_and_model_params()
    test_nodes_history_messages_and_invoke()
    test_nodes_llm_tool_call_and_loop_branches()
    test_nodes_llm_stream_and_reasoning_branches()
    test_nodes_model_result_branches()
    test_nodes_condition_operators()
    test_nodes_condition_node_no_match()
    test_nodes_template_classifier_reranker_document_knowledge()
    test_nodes_tool_and_unsupported()
    test_nodes_engine_resume_with_form_submission()
    test_executor_safe_errors_and_run_error()
    test_executor_workflow_context_branches()
    test_executor_load_scope_branches()
    test_workflow_uploads_upload_branches()
    test_workflow_uploads_resolve_branches()
    test_workflow_uploads_workspace_wrappers()
    test_workflow_access_helpers_and_rate_limit()
    test_workflow_access_external_run_branches()
    test_workflow_access_stream_mapping()
    test_workflow_access_conversations_and_run_listing()
    test_api_endpoint_functions_direct()
    test_workflow_access_application_functions_direct()
    test_executor_manual_run_scenarios()
    test_public_and_api_workflow_access_end_to_end()
    print("WORKFLOW_NODE_COVERAGE_SUITE_OK")


if __name__ == "__main__":
    main()
