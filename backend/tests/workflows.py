"""Workflow engine and API regression suite.

Run from ``backend/`` with ``uv run python -m tests.workflows``.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import tests.support  # noqa: F401

from app.schemas.workflow import WorkflowNode
from app.shareddomain.agents.runtime.tools import AgentToolResult
from app.shareddomain.workflows.engine import (
    NodeExecutionContext,
    NodeResult,
    NodeState,
    WorkflowEngine,
    WorkflowEngineError,
    WorkflowEngineState,
    WorkflowInputRequired,
    WorkflowValidationError,
    validate_graph,
)
from app.shareddomain.workflows.defaults import default_workflow_graph
from tests.support import activate_admin, activate_user, auth_headers, test_client


def test_default_workflow_only_contains_start() -> None:
    graph = default_workflow_graph()

    assert [node.data.type for node in graph.nodes] == ["start"]
    assert graph.edges == []


def test_workflow_interaction_config_rejects_audio_uploads() -> None:
    from pydantic import ValidationError

    from app.schemas.agent import AgentCreateRequest

    try:
        AgentCreateRequest.model_validate(
            {
                "name": "Audio workflow",
                "app_type": "workflow",
                "model_id": "model-1",
                "interaction_config": {
                    "file_upload": True,
                    "file_upload_setting": {"file_upload_type": ["audio"]},
                },
            }
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Workflow configuration accepted audio uploads")


def graph(*, condition: bool = False) -> dict:
    nodes = [
        {
            "id": "start",
            "type": "workflow",
            "position": {"x": 0, "y": 0},
            "data": {"type": "start", "title": "Start", "config": {}},
        }
    ]
    edges = []
    if condition:
        nodes.extend(
            [
                {
                    "id": "condition",
                    "type": "workflow",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "type": "condition",
                        "title": "Condition",
                        "config": {
                            "branch": [
                                {
                                    "id": "yes_branch",
                                    "type": "IF",
                                    "condition": "and",
                                    "conditions": [
                                        {
                                            "field": ["start", "question"],
                                            "compare": "eq",
                                            "value": "yes",
                                        }
                                    ],
                                },
                                {
                                    "id": "no_branch",
                                    "type": "ELSE",
                                    "condition": "and",
                                    "conditions": [],
                                },
                            ]
                        },
                    },
                },
                {
                    "id": "yes",
                    "type": "workflow",
                    "position": {"x": 400, "y": -100},
                    "data": {
                        "type": "variable",
                        "title": "Yes",
                        "config": {"value": "yes"},
                    },
                },
                {
                    "id": "no",
                    "type": "workflow",
                    "position": {"x": 400, "y": 100},
                    "data": {
                        "type": "variable",
                        "title": "No",
                        "config": {"value": "no"},
                    },
                },
            ]
        )
        edges.extend(
            [
                {"id": "e1", "source": "start", "target": "condition"},
                {
                    "id": "e2",
                    "source": "condition",
                    "sourceHandle": "yes_branch",
                    "target": "yes",
                },
                {
                    "id": "e3",
                    "source": "condition",
                    "sourceHandle": "no_branch",
                    "target": "no",
                },
            ]
        )
    else:
        nodes.append(
            {
                "id": "value",
                "type": "workflow",
                "position": {"x": 200, "y": 0},
                "data": {
                    "type": "variable",
                    "title": "Value",
                    "config": {"value": "{{start.question}}"},
                },
            }
        )
        edges.append({"id": "e1", "source": "start", "target": "value"})
    nodes.append(
        {
            "id": "end",
            "type": "workflow",
            "position": {"x": 600, "y": 0},
            "data": {
                "type": "end",
                "title": "End",
                "config": {"outputs": {"result": "done"}},
            },
        }
    )
    if condition:
        edges.extend(
            [
                {"id": "e4", "source": "yes", "target": "end"},
                {"id": "e5", "source": "no", "target": "end"},
            ]
        )
    else:
        edges.append({"id": "e2", "source": "value", "target": "end"})
    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 1}}


def test_workflow_validation_rejects_cycles_and_downstream_references() -> None:
    cyclic = graph()
    cyclic["edges"].append({"id": "cycle", "source": "value", "target": "start"})
    try:
        validate_graph(cyclic)
    except WorkflowValidationError:
        pass
    else:
        raise AssertionError("cyclic workflow was accepted")

    downstream = graph()
    downstream["nodes"][1]["data"]["config"]["value"] = "{{end.result}}"
    try:
        validate_graph(downstream)
    except WorkflowValidationError:
        pass
    else:
        raise AssertionError("downstream workflow reference was accepted")

    with_globals = graph()
    with_globals["nodes"][1]["data"]["config"]["value"] = (
        "{{time}}/{{history_context}}/{{chat_id}}/{{start_time}}"
        "|{{global.time}}/{{global.history_context}}"
    )
    validate_graph(with_globals)

    reserved_global = graph()
    reserved_global["nodes"][1]["id"] = "time"
    reserved_global["edges"][0]["target"] = "time"
    reserved_global["edges"][1]["source"] = "time"
    try:
        validate_graph(reserved_global)
    except WorkflowValidationError as exc:
        assert "reserved global names" in str(exc)
    else:
        raise AssertionError("workflow node used a reserved global name")


def test_workflow_engine_runs_branch_and_join_deterministically() -> None:
    async def run() -> None:
        transitions = []

        async def execute(node, context):
            if node.data.type == "start":
                return NodeResult(outputs=context.workflow_inputs)
            if node.data.type == "condition":
                return NodeResult(selected_handles=frozenset({"yes_branch"}))
            if node.data.type == "variable":
                return NodeResult(outputs={"value": node.id})
            return NodeResult(outputs={"result": context.node_outputs["yes"]["value"]})

        async def finished(transition, state):
            assert state.node_states[transition.node.id] == transition.status
            transitions.append((transition.node.id, transition.status))

        engine = WorkflowEngine(
            graph(condition=True),
            max_steps=10,
            max_model_tokens=100,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        result = await engine.run(
            {"input": "yes"}, execute, on_node_finished=finished
        )
        assert result.outputs == {"result": "yes"}
        assert result.state.node_states["no"] == NodeState.SKIPPED
        assert transitions == [
            ("start", NodeState.SUCCEEDED),
            ("condition", NodeState.SUCCEEDED),
            ("no", NodeState.SKIPPED),
            ("yes", NodeState.SUCCEEDED),
            ("end", NodeState.SUCCEEDED),
        ]

    asyncio.run(run())


def test_condition_node_selects_the_first_matching_branch_or_else() -> None:
    from app.application.workflow_nodes import execute_workflow_node
    from app.schemas.workflow import ConditionNodeConfig

    migrated = ConditionNodeConfig.model_validate(
        {
            "left": "{{start.question}}",
            "operator": "equals",
            "right": 0,
        }
    )
    assert migrated.branch[0].conditions[0].value == "0"

    async def run() -> None:
        node = WorkflowNode.model_validate(graph(condition=True)["nodes"][1])
        node.data.config["branch"].insert(
            1,
            {
                "id": "other_branch",
                "type": "ELSE IF",
                "condition": "or",
                "conditions": [
                    {
                        "field": ["start", "question"],
                        "compare": "contain",
                        "value": "y",
                    }
                ],
            },
        )
        stable_types = ConditionNodeConfig.model_validate(node.data.config).model_dump(
            mode="json"
        )
        stable_types["branch"].insert(
            2,
            {
                "id": "third_branch",
                "type": "ELSE IF 2",
                "condition": "and",
                "conditions": [
                    {
                        "field": ["start", "question"],
                        "compare": "eq",
                        "value": "third",
                    }
                ],
            },
        )
        assert [
            item.type for item in ConditionNodeConfig.model_validate(stable_types).branch
        ] == ["IF", "ELSE IF", "ELSE IF", "ELSE"]
        del stable_types["branch"][1]
        assert [
            item.type for item in ConditionNodeConfig.model_validate(stable_types).branch
        ] == ["IF", "ELSE IF", "ELSE"]
        context = NodeExecutionContext(
            workflow_inputs={},
            node_outputs={"start": {"question": "yes"}},
            remaining_model_tokens=100,
        )
        result = await execute_workflow_node(None, node, context)  # type: ignore[arg-type]
        assert result.selected_handles == frozenset({"yes_branch"})
        assert result.outputs == {"branch_name": "IF"}
        assert result.inputs["conditions"] == [
            {
                "branch_id": "yes_branch",
                "field": ["start", "question"],
                "compare": "eq",
                "value": "yes",
                "matched": True,
            }
        ]

        context = NodeExecutionContext(
            workflow_inputs={},
            node_outputs={"start": {"question": "no"}},
            remaining_model_tokens=100,
        )
        result = await execute_workflow_node(None, node, context)  # type: ignore[arg-type]
        assert result.selected_handles == frozenset({"no_branch"})
        assert result.outputs == {"branch_name": "ELSE"}
        assert [item["branch_id"] for item in result.inputs["conditions"]] == [
            "yes_branch",
            "other_branch",
        ]

    asyncio.run(run())


def test_workflow_engine_returns_enabled_llm_content() -> None:
    async def run() -> None:
        workflow = graph()
        workflow["nodes"][1] = {
            "id": "llm",
            "type": "workflow",
            "position": {"x": 200, "y": 0},
            "data": {
                "type": "llm",
                "title": "LLM",
                "config": {"prompt": "hello", "is_result": True},
            },
        }
        workflow["edges"][0]["target"] = "llm"
        workflow["edges"][1]["source"] = "llm"
        end_outputs = {"result": "end"}

        async def execute(node, context):
            if node.data.type == "llm":
                return NodeResult(outputs={"text": "answer"})
            if node.data.type == "end":
                return NodeResult(outputs=dict(end_outputs))
            return NodeResult(outputs=context.workflow_inputs)

        engine = WorkflowEngine(
            workflow,
            max_steps=3,
            max_model_tokens=100,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        result = await engine.run({"question": "hello"}, execute)
        assert result.outputs == {"result": "end"}
        assert result.state.node_outputs["llm"] == {"text": "answer"}

        end_outputs.clear()
        engine = WorkflowEngine(
            workflow,
            max_steps=3,
            max_model_tokens=100,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        result = await engine.run({"question": "hello"}, execute)
        assert result.outputs == {"result": "answer"}

        end_outputs["result"] = "end"
        workflow["nodes"][1]["data"]["config"]["is_result"] = False
        engine = WorkflowEngine(
            workflow,
            max_steps=3,
            max_model_tokens=100,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        result = await engine.run({"question": "hello"}, execute)
        assert result.outputs == {"result": "end"}

    asyncio.run(run())


def test_workflow_reply_node_modes_and_result_output() -> None:
    from pydantic import ValidationError

    from app.application.workflow_nodes import execute_workflow_node
    from app.schemas.workflow import ReplyNodeConfig

    async def run() -> None:
        context = NodeExecutionContext(
            workflow_inputs={},
            node_outputs={
                "start": {"question": "hi"},
                "value": {"value": {"ok": True}},
            },
            remaining_model_tokens=100,
        )
        referencing = WorkflowNode.model_validate(
            {
                "id": "reply",
                "type": "workflow",
                "position": {"x": 0, "y": 0},
                "data": {
                    "type": "reply-node",
                    "title": "Reply",
                    "config": {
                        "reply_type": "referencing",
                        "fields": [["value", "value"], "Value"],
                    },
                },
            }
        )
        result = await execute_workflow_node(None, referencing, context)  # type: ignore[arg-type]
        assert result.outputs == {"answer": "{'ok': True}"}

        custom = referencing.model_copy(
            update={
                "data": referencing.data.model_copy(
                    update={
                        "config": {
                            "reply_type": "custom",
                            "content": (
                                "{% if value.value.ok %}"
                                "Result: {{ start.question | upper }}"
                                "{% endif %}"
                            ),
                        }
                    }
                )
            }
        )
        result = await execute_workflow_node(None, custom, context)  # type: ignore[arg-type]
        assert result.outputs == {"answer": "Result: HI"}

        try:
            ReplyNodeConfig.model_validate({"reply_type": "referencing", "fields": []})
        except ValidationError:
            pass
        else:
            raise AssertionError("Invalid reply fields were accepted")
        try:
            ReplyNodeConfig.model_validate(
                {
                    "reply_type": "referencing",
                    "fields": [["value", "some field"], "Value"],
                }
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("Unsupported reply reference characters were accepted")
        try:
            ReplyNodeConfig.model_validate(
                {"reply_type": "custom", "content": "{% if %}"}
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("Invalid reply template was accepted")

        downstream = graph()
        downstream["nodes"][1] = custom.model_dump(mode="json")
        downstream["nodes"][1]["data"]["config"]["content"] = (
            "{% if end.result %}invalid{% endif %}"
        )
        downstream["edges"][0]["target"] = "reply"
        downstream["edges"][1]["source"] = "reply"
        try:
            validate_graph(downstream)
        except WorkflowValidationError:
            pass
        else:
            raise AssertionError("Reply template referenced a downstream node")

        workflow = graph()
        result_reply = referencing.model_copy(
            update={
                "data": referencing.data.model_copy(
                    update={
                        "config": {
                            "reply_type": "referencing",
                            "fields": [["start", "question"], "Question"],
                        }
                    }
                )
            }
        )
        workflow["nodes"][1] = result_reply.model_dump(mode="json")
        workflow["edges"][0]["target"] = "reply"
        workflow["edges"][1]["source"] = "reply"

        async def execute(node, execution_context):
            if node.data.type == "reply-node":
                return NodeResult(outputs={"answer": "reply answer"})
            if node.data.type == "end":
                return NodeResult(outputs={"result": "end answer"})
            return NodeResult(outputs={"question": "hello"})

        engine = WorkflowEngine(
            workflow,
            max_steps=3,
            max_model_tokens=100,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        engine_result = await engine.run({"question": "hello"}, execute)
        assert engine_result.outputs == {"result": "end answer"}

        workflow["nodes"][1]["data"]["config"]["is_result"] = False
        engine = WorkflowEngine(
            workflow,
            max_steps=3,
            max_model_tokens=100,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        engine_result = await engine.run({"question": "hello"}, execute)
        assert engine_result.outputs == {"result": "end answer"}

    asyncio.run(run())


def test_workflow_engine_enforces_step_and_token_budgets() -> None:
    async def run() -> None:
        async def execute(node, context):
            return NodeResult(outputs={"result": "ok"}, model_tokens=6)

        step_engine = WorkflowEngine(
            graph(),
            max_steps=2,
            max_model_tokens=100,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        try:
            await step_engine.run({"input": "x"}, execute)
        except WorkflowEngineError as exc:
            assert "step limit" in str(exc)
        else:
            raise AssertionError("step budget was not enforced")

        token_engine = WorkflowEngine(
            graph(),
            max_steps=10,
            max_model_tokens=5,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        token_transitions = []

        async def token_finished(transition, _state):
            token_transitions.append(transition)

        try:
            await token_engine.run(
                {"input": "x"}, execute, on_node_finished=token_finished
            )
        except WorkflowEngineError as exc:
            assert "token budget" in str(exc)
        else:
            raise AssertionError("token budget was not enforced")
        assert len(token_transitions) == 1
        assert token_transitions[0].node.id == "start"
        assert token_transitions[0].status == NodeState.FAILED
        assert "token budget" in (token_transitions[0].error or "")

    asyncio.run(run())


def test_workflow_model_output_limit_uses_provider_native_argument() -> None:
    from pydantic import ValidationError

    from app.application.workflow_nodes import (
        _condition,
        _model_output_limit,
        resolve_value,
    )
    from app.schemas.workflow import KnowledgeNodeConfig

    assert _model_output_limit("openai_compatible", 12) == {"max_tokens": 12}
    assert _model_output_limit("google_genai", 12) == {"max_output_tokens": 12}
    assert _model_output_limit("ollama", 12) == {"num_predict": 12}
    assert _model_output_limit("openai_compatible", 100_000) == {
        "max_tokens": 4096
    }
    assert _condition([1, 2, 3], "len_gt", "2")
    assert _condition(True, "is_true", None)
    assert not _condition(False, "is_true", None)
    assert _condition(False, "is_not_true", None)
    assert _condition(2, "gt", "1.5")
    assert _condition("10", "ge", "2")
    assert _condition([1, "2"], "contain", "2")
    assert _condition("text", "not_contain", "z")
    try:
        _condition(3, "len_gt", "2")
    except ValueError as exc:
        assert "requires a string, array, or object" in str(exc)
    else:
        raise AssertionError("length condition accepted an unsupported value")

    context = NodeExecutionContext(
        workflow_inputs={"files": [{"id": "upload-1"}]},
        node_outputs={"start": {"question": "hi", "files": []}},
        remaining_model_tokens=100,
        globals={
            "time": "2026-08-13 10:00:00",
            "history_context": [{"question": "a", "answer": "b"}],
            "chat_id": "conversation-1",
            "start_time": "2026-08-13T10:00:00+00:00",
        },
    )
    assert resolve_value("{{time}}", context) == "2026-08-13 10:00:00"
    assert resolve_value("{{global.time}}", context) == "2026-08-13 10:00:00"
    assert resolve_value("{{history_context}}", context) == [
        {"question": "a", "answer": "b"}
    ]
    assert resolve_value("{{global.history_context}}", context) == [
        {"question": "a", "answer": "b"}
    ]
    assert resolve_value("{{chat_id}}", context) == "conversation-1"
    assert resolve_value("{{global.chat_id}}", context) == "conversation-1"
    assert resolve_value("{{start.question}}", context) == "hi"
    colliding_context = NodeExecutionContext(
        workflow_inputs={},
        node_outputs={"time": {"value": "node time"}},
        remaining_model_tokens=100,
        globals={"time": "global time"},
    )
    assert resolve_value("{{time}}", colliding_context) == {"value": "node time"}
    assert resolve_value("问：{{global.time}}", context) == "问：2026-08-13 10:00:00"
    assert resolve_value(
        "{{history_context}}", context
    ) == [{"question": "a", "answer": "b"}]
    assert KnowledgeNodeConfig.model_validate(
        {
            "knowledge_base_id": "legacy-base",
            "knowledge_base_ids": ["second-base", "legacy-base"],
            "query": "question",
        }
    ).resolved_knowledge_base_ids == ["legacy-base", "second-base"]
    try:
        KnowledgeNodeConfig.model_validate(
            {
                "query": "question",
                "knowledge_base_ids": [f"base-{index}" for index in range(51)],
            }
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Knowledge node accepted more than 50 knowledge bases")


def test_workflow_model_timeout_uses_specific_safe_error() -> None:
    from app.application.workflow_executor import _safe_node_error
    from app.ports.llm import ModelProviderTimeoutError

    assert (
        _safe_node_error(ModelProviderTimeoutError("Model request timed out."))
        == "Workflow model request timed out."
    )


def test_workflow_resources_come_from_nodes_without_knowledge_limit() -> None:
    from pydantic import ValidationError

    from app.schemas.workflow import KnowledgeNodeConfig, WorkflowGraph
    from app.shareddomain.workflows.services import workflow_resource_references

    knowledge_ids = [f"base-{index}" for index in range(25)]
    assert KnowledgeNodeConfig.model_validate(
        {"query": "q", "knowledge_base_ids": knowledge_ids}
    ).resolved_knowledge_base_ids == knowledge_ids

    parsed = WorkflowGraph.model_validate(
        {
            "nodes": [
                {
                    "id": "knowledge",
                    "type": "workflow",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "knowledge",
                        "title": "Knowledge",
                        "config": {
                            "query": "q",
                            "knowledge_base_ids": knowledge_ids,
                        },
                    },
                },
                {
                    "id": "mcp",
                    "type": "workflow",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "type": "mcp",
                        "title": "MCP",
                        "config": {
                            "server_id": "server-1",
                            "tool_name": "search",
                            "arguments": {},
                        },
                    },
                },
            ],
            "edges": [],
        }
    )
    assert workflow_resource_references(parsed) == (
        knowledge_ids,
        [{"server_id": "server-1", "tool_name": "search"}],
    )
    malformed = parsed.model_dump(mode="json")
    del malformed["nodes"][1]["data"]["config"]["server_id"]
    try:
        workflow_resource_references(WorkflowGraph.model_validate(malformed))
    except ValidationError:
        pass
    else:
        raise AssertionError("Malformed MCP node config bypassed validation")


def test_workflow_resource_validation_batches_knowledge_bases() -> None:
    from unittest.mock import AsyncMock, patch

    from fastapi import HTTPException

    from app.shareddomain.workflows.services import validate_workflow_resources

    knowledge_ids = [f"base-{index}" for index in range(25)]
    workflow = graph()
    workflow["nodes"][1]["data"] = {
        "type": "knowledge",
        "title": "Knowledge",
        "config": {
            "query": "{{start.question}}",
            "knowledge_base_ids": knowledge_ids,
        },
    }
    agent = SimpleNamespace(workspace_id="workspace-1", model_id="model-1")
    actor = SimpleNamespace(id="user-1")

    def rows(*, owner: str = "user-1", status: str = "active") -> list[tuple]:
        return [
            (
                SimpleNamespace(
                    id=knowledge_base_id,
                    workspace_id="workspace-1",
                    created_by_user_id=owner,
                    status=status,
                ),
                None,
            )
            for knowledge_base_id in knowledge_ids
        ]

    async def validate(knowledge_rows: list[tuple]) -> int | None:
        batch = AsyncMock(return_value=knowledge_rows)
        with patch(
            "app.shareddomain.workflows.services.get_agent_model",
            new=AsyncMock(return_value=object()),
        ), patch(
            "app.shareddomain.workflows.services.knowledge_base_repository."
            "list_knowledge_bases_with_user_grants",
            new=batch,
        ):
            try:
                await validate_workflow_resources(
                    object(),  # type: ignore[arg-type]
                    agent,  # type: ignore[arg-type]
                    workflow,
                    actor,  # type: ignore[arg-type]
                    "member",
                )
            except HTTPException as exc:
                status_code = exc.status_code
            else:
                status_code = None
        batch.assert_awaited_once()
        assert batch.await_args.args[2] == knowledge_ids
        return status_code

    async def run() -> None:
        assert await validate(rows()) is None
        assert await validate(rows()[:-1]) == 404
        assert await validate(rows(owner="another-user")) == 403
        assert await validate(rows(status="archived")) == 422

    asyncio.run(run())


def test_workflow_context_batches_prior_node_executions() -> None:
    from unittest.mock import AsyncMock, patch

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
            node_id="llm-1",
            status="succeeded",
            outputs={"text": "old node answer"},
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
        list_runs = AsyncMock(return_value=prior)
        list_executions = AsyncMock(return_value=executions)
        with patch(
            "app.application.workflow_executor.get_session_factory",
            return_value=lambda: SessionContext(),
        ), patch(
            "app.application.workflow_executor.agent_repository.list_agent_runs",
            new=list_runs,
        ), patch(
            "app.application.workflow_executor.workflow_repository."
            "list_node_executions_for_runs",
            new=list_executions,
        ):
            workflow_globals, histories = await _workflow_context(
                run,  # type: ignore[arg-type]
                workflow,
            )

        list_runs.assert_awaited_once()
        list_executions.assert_awaited_once()
        assert list_executions.await_args.args[1] == ["run-new", "run-old"]
        assert workflow_globals["history_context"] == [
            {"question": "old", "answer": "old answer"},
            {"question": "new", "answer": {"value": "new"}},
        ]
        assert histories == {
            "llm-1": [
                {"question": "old", "answer": "old node answer"},
                {"question": "new", "answer": "new node answer"},
            ]
        }
        start_time = datetime.fromisoformat(workflow_globals["start_time"])
        assert start_time.utcoffset() == timedelta(0)
        assert workflow_globals["time"] == start_time.strftime("%Y-%m-%d %H:%M:%S")

    asyncio.run(check())


def test_workflow_start_node_outputs_question_files_and_globals() -> None:
    from types import SimpleNamespace

    from app.application.workflow_nodes import execute_workflow_node
    from app.schemas.workflow import WorkflowNode

    async def run() -> None:
        scope = SimpleNamespace(
            run=SimpleNamespace(goal="what is the weather?"),
        )
        node = WorkflowNode.model_validate(
            {
                "id": "start",
                "position": {"x": 0, "y": 0},
                "data": {"type": "start", "title": "Start", "config": {}},
            }
        )
        result = await execute_workflow_node(
            scope,
            node,
            NodeExecutionContext(
                workflow_inputs={
                    "question": "what is the weather?",
                    "files": [{"id": "upload-1"}],
                },
                node_outputs={},
                remaining_model_tokens=100,
                globals={
                    "time": "2026-08-13 10:00:00",
                    "history_context": [],
                    "chat_id": "conversation-1",
                    "start_time": "2026-08-13T10:00:00+00:00",
                },
            ),
        )
        assert result.outputs == {
            "files": [{"id": "upload-1"}],
            "question": "what is the weather?",
            "time": "2026-08-13 10:00:00",
            "history_context": [],
            "chat_id": "conversation-1",
            "start_time": "2026-08-13T10:00:00+00:00",
        }

    asyncio.run(run())


def test_workflow_knowledge_node_limits_and_joins_results() -> None:
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.application.workflow_nodes import execute_workflow_node
    from app.schemas.workflow import WorkflowNode
    from app.shareddomain.workflows.engine import NodeExecutionContext

    class FakeTool:
        async def ainvoke(self, arguments):
            assert arguments == {
                "query": "question",
                "limit": 2,
                "search_mode": "embedding",
                "similarity": 0.6,
            }
            return SimpleNamespace(
                is_error=False,
                summary="ok",
                content="",
                output={
                    "hits": [
                        {
                            "chunk_id": "chunk-1",
                            "content": "first",
                            "distance": 0.3,
                            "similarity": 0.85,
                            "trace_id": "trace-1",
                            "rerank_status": "applied",
                            "sources": ["vector", "reference"],
                            "reference_hops": 1,
                        },
                        {
                            "chunk_id": "chunk-2",
                            "content": "second",
                            "distance": 0.9,
                            "similarity": 0.55,
                            "trace_id": "trace-2",
                            "rerank_status": "fallback",
                            "sources": ["keywords"],
                            "reference_hops": 0,
                        },
                        {
                            "chunk_id": "chunk-3",
                            "content": "third",
                            "distance": 0.2,
                            "similarity": 0.9,
                            "trace_id": "trace-3",
                            "rerank_status": "not_configured",
                        },
                    ],
                    "retrieval_stats": [
                        {
                            "knowledge_base_id": "base-1",
                            "trace_id": "trace-1",
                            "rerank_status": "applied",
                        },
                        {
                            "knowledge_base_id": "base-2",
                            "trace_id": "trace-2",
                            "rerank_status": "fallback",
                        },
                    ],
                    "evidence_status": "found",
                },
            )

    async def run() -> None:
        scope = SimpleNamespace(
            knowledge_bases={
                "base-1": SimpleNamespace(id="base-1"),
                "base-2": SimpleNamespace(id="base-2"),
            },
            run=SimpleNamespace(workspace_id="workspace-1"),
            actor=SimpleNamespace(),
            workspace_role="member",
            settings=SimpleNamespace(),
        )
        node = WorkflowNode.model_validate(
            {
                "id": "knowledge",
                "position": {"x": 0, "y": 0},
                "data": {
                    "type": "knowledge",
                    "title": "Knowledge",
                    "config": {
                        "knowledge_base_ids": ["base-1", "base-2"],
                        "query": "question",
                        "limit": 2,
                    },
                },
            }
        )
        with patch(
            "app.application.workflow_nodes.build_knowledge_search_tool",
            return_value=FakeTool(),
        ) as build_tool:
            result = await execute_workflow_node(
                scope,
                node,
                NodeExecutionContext(
                    workflow_inputs={},
                    node_outputs={},
                    remaining_model_tokens=100,
                ),
            )

        assert [item.id for item in build_tool.call_args.args[0]] == [
            "base-1",
            "base-2",
        ]
        assert [item["chunk_id"] for item in result.outputs["hits"]] == [
            "chunk-1",
            "chunk-2",
        ]
        assert result.outputs["content"] == "first\n\nsecond"
        assert result.outputs["data"] == "first\n\nsecond"
        assert result.outputs["paragraph_list"][0]["distance"] == 0.3
        assert result.outputs["paragraph_list"][0]["similarity"] == 0.85
        assert [
            (
                item["chunk_id"],
                item["trace_id"],
                item["rerank_status"],
                item["sources"],
                item["reference_hops"],
            )
            for item in result.outputs["paragraph_list"]
        ] == [
            (
                "chunk-1",
                "trace-1",
                "applied",
                ["vector", "reference"],
                1,
            ),
            ("chunk-2", "trace-2", "fallback", ["keywords"], 0),
        ]
        assert result.outputs["retrieval_stats"] == [
            {
                "knowledge_base_id": "base-1",
                "trace_id": "trace-1",
                "rerank_status": "applied",
            },
            {
                "knowledge_base_id": "base-2",
                "trace_id": "trace-2",
                "rerank_status": "fallback",
            },
        ]
        assert [
            item["content"] for item in result.outputs["is_hit_handling_method_list"]
        ] == ["first"]
        assert result.outputs["directly_return"] == "first"

    asyncio.run(run())


def test_workflow_knowledge_node_maxkb_settings_and_truncation() -> None:
    from types import SimpleNamespace
    from unittest.mock import patch

    from pydantic import ValidationError

    from app.application.workflow_nodes import execute_workflow_node
    from app.schemas.workflow import KnowledgeNodeConfig, WorkflowNode
    from app.shareddomain.workflows.engine import NodeExecutionContext

    assert KnowledgeNodeConfig.model_validate(
        {"query": "q", "knowledge_base_ids": ["base-1"]}
    ).similarity == 0.6
    assert (
        KnowledgeNodeConfig.model_validate(
            {"query": "q", "knowledge_base_ids": ["base-1"]}
        ).search_mode
        == "embedding"
    )
    assert (
        KnowledgeNodeConfig.model_validate(
            {"query": "q", "knowledge_base_ids": ["base-1"]}
        ).max_paragraph_char_number
        == 5000
    )
    assert KnowledgeNodeConfig.model_validate(
        {
            "query": "q",
            "knowledge_base_ids": ["base-1"],
            "source_dataset_id_list": ["base-1"],
        }
    ).source_dataset_id_list == ["base-1"]
    try:
        KnowledgeNodeConfig.model_validate(
            {
                "query": "q",
                "knowledge_base_ids": ["base-1"],
                "similarity": 1.1,
            }
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Knowledge node accepted similarity above 1")

    class FakeTool:
        async def ainvoke(self, arguments):
            assert arguments == {
                "query": "question",
                "limit": 8,
                "search_mode": "keywords",
                "similarity": 0.8,
            }
            return SimpleNamespace(
                is_error=False,
                summary="ok",
                content="",
                output={
                    "hits": [
                        {
                            "knowledge_base": "KB",
                            "document": "doc-a",
                            "chunk_id": "chunk-1",
                            "document_id": "doc-1",
                            "content": "alpha beta",
                            "distance": 0.1,
                            "similarity": 0.95,
                        }
                    ],
                    "evidence_status": "found",
                },
            )

    async def run() -> None:
        scope = SimpleNamespace(
            knowledge_bases={"base-1": SimpleNamespace(id="base-1")},
            run=SimpleNamespace(workspace_id="workspace-1"),
            actor=SimpleNamespace(),
            workspace_role="member",
            settings=SimpleNamespace(),
        )
        node = WorkflowNode.model_validate(
            {
                "id": "knowledge",
                "position": {"x": 0, "y": 0},
                "data": {
                    "type": "knowledge",
                    "title": "Knowledge",
                    "config": {
                        "knowledge_base_ids": ["base-1"],
                        "query": "question",
                        "limit": 8,
                        "similarity": 0.8,
                        "search_mode": "keywords",
                        "max_paragraph_char_number": 5,
                    },
                },
            }
        )
        with patch(
            "app.application.workflow_nodes.build_knowledge_search_tool",
            return_value=FakeTool(),
        ):
            result = await execute_workflow_node(
                scope,
                node,
                NodeExecutionContext(
                    workflow_inputs={},
                    node_outputs={},
                    remaining_model_tokens=100,
                ),
            )
        assert result.outputs["paragraph_list"] == [
            {
                "knowledge_base": "KB",
                "document": "doc-a",
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "content": "alpha beta",
                "distance": 0.1,
                "similarity": 0.95,
            }
        ]
        assert result.outputs["is_hit_handling_method_list"] == [
            result.outputs["paragraph_list"][0]
        ]
        # data 按最大引用字符数截断；directly_return 不截断
        assert result.outputs["data"] == "alpha"
        assert result.outputs["directly_return"] == "alpha beta"
        assert result.outputs["content"] == "alpha beta"
        assert result.inputs["search_mode"] == "keywords"
        assert result.inputs["similarity"] == 0.8

    asyncio.run(run())


def test_workflow_reranker_form_and_document_nodes() -> None:
    from unittest.mock import patch

    from app.application.workflow_nodes import execute_workflow_node

    class FakeReranker:
        def rerank(self, query, documents):
            assert query == "question"
            assert documents == ["first", "second"]
            return [
                {"index": 1, "relevance_score": 0.9},
                {"index": 1, "relevance_score": 0.8},
                {"index": 0, "relevance_score": float("nan")},
                {"index": 0, "relevance_score": 0.4},
            ]

    async def run() -> None:
        context = NodeExecutionContext(
            workflow_inputs={},
            node_outputs={
                "knowledge": {
                    "paragraph_list": [
                        {"content": "first", "document_id": "one"},
                        {"content": "second", "document_id": "two"},
                    ]
                }
            },
            remaining_model_tokens=100,
        )
        reranker = WorkflowNode.model_validate(
            {
                "id": "reranker",
                "position": {"x": 0, "y": 0},
                "data": {
                    "type": "reranker-node",
                    "title": "Reranker",
                    "config": {
                        "reranker_model_id": "reranker-1",
                        "question_reference_address": "question",
                        "reranker_reference_list": [
                            "{{knowledge.paragraph_list}}"
                        ],
                        "reranker_setting": {
                            "top_n": 2,
                            "similarity": 0.5,
                            "max_paragraph_char_number": 100,
                        },
                    },
                },
            }
        )
        scope = SimpleNamespace(
            models={
                "reranker-1": SimpleNamespace(model_type="RERANKER")
            },
            settings=SimpleNamespace(),
            form_submissions={},
        )
        with patch(
            "app.application.workflow_nodes.build_reranker",
            return_value=FakeReranker(),
        ):
            reranked = await execute_workflow_node(scope, reranker, context)
        assert reranked.outputs == {
            "result_list": [
                {
                    "content": "second",
                    "document_id": "two",
                    "similarity": 0.9,
                }
            ],
            "result": "second",
        }

        form = WorkflowNode.model_validate(
            {
                "id": "form",
                "position": {"x": 0, "y": 0},
                "data": {
                    "type": "form-node",
                    "title": "Form",
                    "config": {
                        "form_field_list": [
                            {
                                "variable": "email",
                                "name": "Email",
                                "type": "input",
                                "is_required": True,
                            }
                        ],
                        "form_content_format": (
                            "Before {{ knowledge.paragraph_list.0.content }} "
                            "{{ form }} After"
                        ),
                    },
                },
            }
        )
        waiting = await execute_workflow_node(scope, form, context)
        assert waiting.interrupt == {
            "runtime_node_id": "form",
            "content": "Before first {{ form }} After",
            "fields": [
                {
                    "variable": "email",
                    "name": "Email",
                    "type": "input",
                    "is_required": True,
                    "default_value": None,
                    "show_default_value": False,
                    "optionList": [],
                }
            ],
        }
        scope.form_submissions["form"] = {"email": "user@example.com"}
        submitted = await execute_workflow_node(scope, form, context)
        assert submitted.outputs["email"] == "user@example.com"
        assert submitted.outputs["form_data"] == {"email": "user@example.com"}

        document = WorkflowNode.model_validate(
            {
                "id": "document",
                "position": {"x": 0, "y": 0},
                "data": {
                    "type": "document-extract-node",
                    "title": "Document",
                    "config": {
                        "document_list": [
                            {"file_id": "file-1", "name": "a.txt", "content": "hello"}
                        ]
                    },
                },
            }
        )
        extracted = await execute_workflow_node(scope, document, context)
        assert extracted.outputs == {"content": "--- a.txt ---\nhello"}

        graph_form = form.model_dump(mode="json")
        graph_form["data"]["config"]["form_content_format"] = "Before {{ form }} After"
        graph_value = {
            "nodes": [
                {
                    "id": "start",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "start", "title": "Start", "config": {}},
                },
                graph_form,
                {
                    "id": "end",
                    "position": {"x": 2, "y": 0},
                    "data": {
                        "type": "end",
                        "title": "End",
                        "config": {"outputs": {"result": "{{form.email}}"}},
                    },
                },
            ],
            "edges": [
                {"id": "one", "source": "start", "target": "form"},
                {"id": "two", "source": "form", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }
        engine = WorkflowEngine(
            graph_value,
            max_steps=10,
            max_model_tokens=100,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )

        paused_state: WorkflowEngineState | None = None

        async def execute(node, _context):
            if node.data.type == "start":
                return NodeResult(outputs={})
            return NodeResult(interrupt={"runtime_node_id": "form"})

        async def capture_state(_transition, state):
            nonlocal paused_state
            paused_state = WorkflowEngineState.from_dict(state.to_dict())

        try:
            await engine.run({}, execute, on_node_finished=capture_state)
        except WorkflowInputRequired as exc:
            assert exc.form == {"runtime_node_id": "form"}
        else:
            raise AssertionError("Form node did not interrupt the workflow")
        assert paused_state is not None

        async def resume(node, context):
            if node.data.type == "form-node":
                return NodeResult(outputs={"email": "user@example.com"})
            assert node.data.type == "end"
            return NodeResult(outputs={"result": context.node_outputs["form"]["email"]})

        completed = await engine.run({}, resume, state=paused_state)
        assert completed.outputs == {"result": "user@example.com"}

    asyncio.run(run())


def test_workflow_engine_propagates_worker_cancellation() -> None:
    async def run() -> None:
        async def execute(node, context):
            raise asyncio.CancelledError

        engine = WorkflowEngine(
            graph(),
            max_steps=10,
            max_model_tokens=100,
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
        try:
            await engine.run({"input": "x"}, execute)
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("worker cancellation was swallowed")

    asyncio.run(run())


def test_upload_cleanup_tasks_are_registered() -> None:
    from app.infrastructure.celery import celery_app

    assert "app.uploads.cleanup_storage" in celery_app.tasks
    assert "app.uploads.recover_storage_cleanups" in celery_app.tasks
    assert (
        celery_app.conf.beat_schedule["recover-upload-storage-cleanups"]["task"]
        == "app.uploads.recover_storage_cleanups"
    )


def test_interaction_config_migration_upgrades_prerequisites() -> None:
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "202608120004_agent_interaction_config.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_interaction_config_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("CREATE TABLE users (id TEXT PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE agents (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, "
                "UNIQUE (workspace_id, id))"
            )
        )
        connection.execute(text("CREATE TABLE agent_runs (id TEXT PRIMARY KEY)"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        inspector = inspect(connection)
        assert {
            "workflow_uploads",
            "workflow_upload_storage_cleanups",
        }.issubset(inspector.get_table_names())
        cleanup_columns = {
            column["name"]
            for column in inspector.get_columns("workflow_upload_storage_cleanups")
        }
        assert {
            "workspace_id",
            "uploaded_by_user_id",
            "object_key",
            "size_bytes",
            "next_attempt_at",
        }.issubset(cleanup_columns)


def assert_upload_cleanup_removes_object(upload_id: str) -> None:
    from app.infrastructure.object_storage import create_object_storage
    from app.infrastructure.repositories import workflow as workflow_repository
    from app.infrastructure.session import get_session_factory
    from app.shareddomain.workflows.uploads import (
        prepare_due_upload_cleanups,
        run_upload_storage_cleanup,
    )

    async def run() -> None:
        runtime_settings = tests.support.settings()
        cleanup_ids = await prepare_due_upload_cleanups()
        object_path = None
        async with get_session_factory()() as db:
            for cleanup_id in cleanup_ids:
                cleanup = await workflow_repository.lock_upload_cleanup(db, cleanup_id)
                if cleanup is not None and cleanup.object_key.endswith(upload_id):
                    object_path = create_object_storage(
                        runtime_settings.knowledge_storage_dir
                    ).path(cleanup.object_key)
                    break
        assert object_path is not None and object_path.exists()
        for cleanup_id in cleanup_ids:
            await run_upload_storage_cleanup(cleanup_id, runtime_settings)
        assert not object_path.exists()

    asyncio.run(run())


async def assert_exhausted_workflow_closes_running_node(run_id: str) -> None:
    from app.infrastructure.model_utils import utc_now
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import workflow as workflow_repository
    from app.infrastructure.session import get_session_factory

    now = utc_now()
    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        assert run is not None
        run.status = "running_v2"
        run.attempts = run.max_attempts
        run.worker_task_id = "expired-workflow-worker"
        run.lease_expires_at = now - timedelta(seconds=1)
        run.finished_at = None
        await agent_repository.save_agent_run(db, run)
        started = await workflow_repository.start_node_execution(
            db,
            workspace_id=run.workspace_id,
            run_id=run.id,
            worker_task_id="expired-workflow-worker",
            node_id="start",
            node_type="start",
            sequence=1,
            started_at=now - timedelta(seconds=2),
        )
        assert started is not None
        await db.commit()

    async with get_session_factory()() as db:
        assert len(
            await agent_repository.fail_exhausted_agent_run_ids(
                db,
                now,
                generation="unified",
            )
        ) == 1
        await db.commit()
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        nodes = await workflow_repository.list_node_executions(db, run_id)

    assert run is not None and run.status == "failed"
    start = next(item for item in nodes if item.node_id == "start")
    assert start.status == "failed"
    assert start.finished_at is not None
    assert "retry limit reached" in (start.error or "")


async def assert_first_claim_sets_deadline_once(run_id: str) -> None:
    from app.infrastructure.model_utils import utc_now
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import workflow as workflow_repository
    from app.infrastructure.session import get_session_factory

    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        detail = await workflow_repository.get_run_detail(db, run_id)
        assert run is not None and detail is not None
        original_deadline = detail.deadline_at
        run.attempts = 1
        run.worker_task_id = "deadline-worker-1"
        await agent_repository.save_agent_run(db, run)
        await workflow_repository.set_first_run_deadline(
            db,
            run_id,
            "deadline-worker-1",
            utc_now() + timedelta(seconds=60),
        )
        await db.commit()

    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        detail = await workflow_repository.get_run_detail(db, run_id)
        assert run is not None and detail is not None
        first_deadline = detail.deadline_at
        assert first_deadline != original_deadline
        run.attempts = 2
        run.worker_task_id = "deadline-worker-2"
        await agent_repository.save_agent_run(db, run)
        await workflow_repository.set_first_run_deadline(
            db,
            run_id,
            "deadline-worker-2",
            utc_now() + timedelta(seconds=120),
        )
        await db.commit()

    async with get_session_factory()() as db:
        detail = await workflow_repository.get_run_detail(db, run_id)
        assert detail is not None and detail.deadline_at == first_deadline


def test_workflow_api_definition_publish_run_and_audit() -> None:
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
        workflow = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=headers,
            json={
                "name": "Release Workflow",
                "app_type": "workflow",
                "model_id": model.json()["id"],
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

        agent_runs = client.get(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}/runs",
            headers=headers,
        )
        assert agent_runs.status_code == 409, agent_runs.text
        agent_run = client.get(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}/runs/missing",
            headers=headers,
        )
        assert agent_run.status_code == 409, agent_run.text

        definition = client.get(f"{base}/definition", headers=headers)
        assert definition.status_code == 200, definition.text
        assert definition.json()["revision"] == 1
        workflow_graph = definition.json()["graph"]
        assert [node["data"]["type"] for node in workflow_graph["nodes"]] == ["start"]
        assert workflow_graph["edges"] == []
        incomplete = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 1, "graph": workflow_graph},
        )
        assert incomplete.status_code == 200, incomplete.text
        assert incomplete.json()["revision"] == 2
        workflow_graph["nodes"].extend(
            [
                {
                    "id": "value",
                    "type": "workflow",
                    "position": {"x": 270, "y": 180},
                    "data": {
                        "type": "variable",
                        "title": "Value",
                        "config": {"value": "{{start.question}}"},
                    },
                },
                {
                    "id": "end",
                    "type": "workflow",
                    "position": {"x": 460, "y": 180},
                    "data": {
                        "type": "end",
                        "title": "End",
                        "config": {"outputs": {"result": "{{value.value}}"}},
                    },
                },
            ]
        )
        workflow_graph["edges"] = [
            {"id": "start-value", "source": "start", "target": "value"},
            {"id": "value-end", "source": "value", "target": "end"},
        ]
        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 2, "graph": workflow_graph},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"] == 3
        conflict = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 2, "graph": workflow_graph},
        )
        assert conflict.status_code == 409, conflict.text

        published = client.post(f"{base}/publish", headers=headers)
        assert published.status_code == 201, published.text
        assert published.json()["version_number"] == 1
        assert published.json()["definition_revision"] == 3

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
        member_draft = client.post(
            f"{base}/runs",
            headers=member_headers,
            json={"source": "draft", "question": "not-allowed"},
        )
        assert member_draft.status_code == 403, member_draft.text

        workflow_graph["nodes"][2]["data"]["config"] = {
            "outputs": {"result": "draft-two"}
        }
        next_draft = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 3, "graph": workflow_graph},
        )
        assert next_draft.status_code == 200, next_draft.text
        assert next_draft.json()["revision"] == 4

        draft_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "draft", "question": "release-ready"},
        )
        assert draft_run.status_code == 201, draft_run.text
        assert draft_run.json()["status"] == "succeeded", draft_run.text
        assert draft_run.json()["outputs"] == {"result": "draft-two"}
        assert draft_run.json()["inputs"] == {"question": "release-ready"}
        run_id = draft_run.json()["id"]
        nodes = client.get(f"{base}/runs/{run_id}/nodes", headers=headers)
        assert nodes.status_code == 200, nodes.text
        assert [item["status"] for item in nodes.json()["items"]] == [
            "succeeded",
            "succeeded",
            "succeeded",
        ]
        assert nodes.json()["items"][0]["outputs"]["question"] == "release-ready"
        assert nodes.json()["items"][1]["outputs"] == {"value": "release-ready"}
        draft_feedback = client.post(
            f"{base}/runs/{run_id}/feedback",
            headers=headers,
            json={"value": "positive"},
        )
        assert draft_feedback.status_code == 200, draft_feedback.text
        assert draft_feedback.json()["feedback"] == "positive"
        draft_feedback_updated_at = draft_feedback.json()["feedback_updated_at"]
        assert draft_feedback_updated_at
        repeated_draft_feedback = client.post(
            f"{base}/runs/{run_id}/feedback",
            headers=headers,
            json={"value": "positive"},
        )
        assert repeated_draft_feedback.status_code == 200
        assert (
            repeated_draft_feedback.json()["feedback_updated_at"]
            == draft_feedback_updated_at
        )
        cross_draft_feedback = client.post(
            f"{base}/runs/{run_id}/feedback",
            headers=member_headers,
            json={"value": "negative"},
        )
        assert cross_draft_feedback.status_code == 404, cross_draft_feedback.text
        regenerated_draft = client.post(
            f"{base}/runs/{run_id}/regenerate",
            headers=headers,
        )
        assert regenerated_draft.status_code == 200, regenerated_draft.text
        regenerated_draft_payload = regenerated_draft.json()
        assert regenerated_draft_payload["status"] == "succeeded"
        assert regenerated_draft_payload["source"] == "draft"
        assert regenerated_draft_payload["inputs"] == {"question": "release-ready"}
        assert regenerated_draft_payload["outputs"] == {"result": "draft-two"}
        assert regenerated_draft_payload["regenerated_from_run_id"] == run_id
        assert regenerated_draft_payload["feedback"] is None
        original_draft = client.get(f"{base}/runs/{run_id}", headers=headers)
        assert original_draft.status_code == 200
        assert original_draft.json()["feedback"] == "positive"
        logical_draft_runs = client.get(f"{base}/runs", headers=headers)
        assert logical_draft_runs.status_code == 200, logical_draft_runs.text
        assert logical_draft_runs.json()[0]["id"] == regenerated_draft_payload["id"]

        events = client.get(f"{base}/runs/{run_id}/stream", headers=headers)
        assert events.status_code == 200, events.text
        event_types = [json.loads(line)["type"] for line in events.text.splitlines()]
        assert event_types[0] == "run"
        assert "workflow_node" in event_types
        assert event_types[-1] == "complete"
        asyncio.run(assert_first_claim_sets_deadline_once(run_id))
        asyncio.run(assert_exhausted_workflow_closes_running_node(run_id))

        published_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={
                "source": "published",
                "version_number": 1,
                "question": "version-one",
            },
        )
        assert published_run.status_code == 201, published_run.text
        assert published_run.json()["status"] == "succeeded"
        assert published_run.json()["outputs"] == {"result": "version-one"}
        assert published_run.json()["version_number"] == 1

        member_run = client.post(
            f"{base}/runs",
            headers=member_headers,
            json={
                "source": "published",
                "version_number": 1,
                "question": "member-version",
            },
        )
        assert member_run.status_code == 201, member_run.text
        assert member_run.json()["outputs"] == {"result": "member-version"}
        member_own_run = client.get(
            f"{base}/runs/{member_run.json()['id']}", headers=member_headers
        )
        assert member_own_run.status_code == 200, member_own_run.text
        member_admin_run = client.get(
            f"{base}/runs/{run_id}", headers=member_headers
        )
        assert member_admin_run.status_code == 404, member_admin_run.text
        admin_member_run = client.get(
            f"{base}/runs/{member_run.json()['id']}", headers=headers
        )
        assert admin_member_run.status_code == 404, admin_member_run.text

        versions = client.get(f"{base}/versions", headers=headers)
        assert versions.status_code == 200, versions.text
        assert [item["version_number"] for item in versions.json()["items"]] == [1]
        stale_restore = client.post(
            f"{base}/versions/1/restore",
            headers=headers,
            json={"expected_revision": 3},
        )
        assert stale_restore.status_code == 409, stale_restore.text
        restored = client.post(
            f"{base}/versions/1/restore",
            headers=headers,
            json={"expected_revision": 4},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["revision"] == 5
        assert restored.json()["graph"]["nodes"][2]["data"]["config"] == {
            "outputs": {"result": "{{value.value}}"}
        }

        failure_graph = restored.json()["graph"]
        failure_graph["nodes"][1]["data"]["config"] = {
            "value": "{{start.missing}}"
        }
        failure_draft = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 5, "graph": failure_graph},
        )
        assert failure_draft.status_code == 200, failure_draft.text
        failed_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "draft", "question": "runtime-error"},
        )
        assert failed_run.status_code == 201, failed_run.text
        assert failed_run.json()["status"] == "failed"
        assert "reference path not found" in failed_run.json()["last_error"]
        failed_feedback = client.post(
            f"{base}/runs/{failed_run.json()['id']}/feedback",
            headers=headers,
            json={"value": "negative"},
        )
        assert failed_feedback.status_code == 409, failed_feedback.text
        failed_regeneration = client.post(
            f"{base}/runs/{failed_run.json()['id']}/regenerate",
            headers=headers,
        )
        assert failed_regeneration.status_code == 409, failed_regeneration.text
        failed_nodes = client.get(
            f"{base}/runs/{failed_run.json()['id']}/nodes", headers=headers
        )
        assert failed_nodes.status_code == 200, failed_nodes.text
        assert [item["status"] for item in failed_nodes.json()["items"]] == [
            "succeeded",
            "failed",
        ]
        assert "reference path not found" in failed_nodes.json()["items"][1]["error"]

        console_uploaded = client.post(
            f"{base}/uploads",
            headers=headers,
            files={"files": ("debug.txt", b"debug attachment", "text/plain")},
        )
        assert console_uploaded.status_code == 201, console_uploaded.text
        console_upload_id = console_uploaded.json()[0]["id"]
        console_file_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={
                "source": "draft",
                "question": "debug-file",
                "file_ids": [console_upload_id],
            },
        )
        assert console_file_run.status_code == 201, console_file_run.text
        assert console_file_run.json()["inputs"]["files"] == [
            {
                "id": console_upload_id,
                "name": "debug.txt",
                "content_type": "text/plain",
                "size_bytes": 16,
                "category": "document",
            }
        ]
        reused_console_upload = client.post(
            f"{base}/runs",
            headers=headers,
            json={"question": "reuse", "file_ids": [console_upload_id]},
        )
        assert reused_console_upload.status_code == 404, reused_console_upload.text
        assert_upload_cleanup_removes_object(console_upload_id)

        wrong_runtime = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}/runs",
            headers=headers,
            json={"goal": "must not run as an agent"},
        )
        assert wrong_runtime.status_code == 409, wrong_runtime.text
        type_change = client.patch(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}",
            headers=headers,
            json={"app_type": "agent"},
        )
        assert type_change.status_code == 409, type_change.text
        credentials = client.get(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}/api-credentials",
            headers=headers,
        )
        assert credentials.status_code == 200, credentials.text

        public_profile = client.get(
            f"/api/v1/public/workflows/{workflow_id}/profile",
            headers=member_headers,
        )
        assert public_profile.status_code == 200, public_profile.text
        assert "inputs" not in public_profile.json(), public_profile.json()
        assert public_profile.json()["interaction_config"] == {
            "prologue": "Choose inputs to start.",
            "tts_type": "BROWSER",
            "file_upload": True,
            "file_upload_setting": {
                "file_upload_type": ["document"],
            },
            "user_input_title": "Release options",
        }
        wrong_public_runtime = client.get(
            f"/api/v1/public/agents/{workflow_id}/profile",
            headers=member_headers,
        )
        assert wrong_public_runtime.status_code == 404, wrong_public_runtime.text

        uploaded = client.post(
            f"/api/v1/public/workflows/{workflow_id}/uploads",
            headers=member_headers,
            files={"files": ("notes.txt", b"release notes", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.json()[0]["filename"] == "notes.txt"
        upload_id = uploaded.json()[0]["id"]
        restored_for_policy = client.post(
            f"{base}/versions/1/restore",
            headers=headers,
            json={"expected_revision": 6},
        )
        assert restored_for_policy.status_code == 200, restored_for_policy.text
        image_only = client.patch(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}",
            headers=headers,
            json={
                "interaction_config": {
                    "prologue": "Choose inputs to start.",
                    "tts_type": "BROWSER",
                    "file_upload": True,
                    "file_upload_setting": {
                        "file_upload_type": ["image"],
                    },
                    "user_input_title": "Release options",
                }
            },
        )
        assert image_only.status_code == 200, image_only.text
        assert client.post(f"{base}/publish", headers=headers).status_code == 201
        stale_policy = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs",
            headers=member_headers,
            json={"question": "stale", "file_ids": [upload_id]},
        )
        assert stale_policy.status_code == 422, stale_policy.text
        document_only = client.patch(
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
        assert document_only.status_code == 200, document_only.text
        assert client.post(f"{base}/publish", headers=headers).status_code == 201
        unlimited_upload = client.post(
            f"/api/v1/public/workflows/{workflow_id}/uploads",
            headers=member_headers,
            files=[
                (
                    "files",
                    ("large.txt", b"x" * (1024 * 1024 + 1), "text/plain"),
                ),
                *[
                    ("files", (f"extra-{index}.txt", b"text", "text/plain"))
                    for index in range(9)
                ],
            ],
        )
        assert unlimited_upload.status_code == 201, unlimited_upload.text
        unlimited_upload_ids = [item["id"] for item in unlimited_upload.json()]
        assert len(unlimited_upload_ids) == 10

        public_run = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs",
            headers=member_headers,
            json={
                "question": "public-workflow",
                "file_ids": [upload_id, *unlimited_upload_ids],
            },
        )
        assert public_run.status_code == 201, public_run.text
        public_payload = public_run.json()
        assert public_payload["status"] == "succeeded"
        assert public_payload["outputs"] == {"result": "public-workflow"}
        assert public_payload["inputs"]["question"] == "public-workflow"
        assert public_payload["inputs"]["files"][0] == {
            "id": upload_id,
            "name": "notes.txt",
            "content_type": "text/plain",
            "size_bytes": 13,
            "category": "document",
        }
        assert len(public_payload["inputs"]["files"]) == 11
        public_feedback = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs/{public_payload['id']}/feedback",
            headers=member_headers,
            json={"value": "negative"},
        )
        assert public_feedback.status_code == 200, public_feedback.text
        assert public_feedback.json()["feedback"] == "negative"
        cross_public_feedback = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs/{public_payload['id']}/feedback",
            headers=headers,
            json={"value": "positive"},
        )
        assert cross_public_feedback.status_code == 404, cross_public_feedback.text
        cross_public_regeneration = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs/{public_payload['id']}/regenerate",
            headers=headers,
        )
        assert cross_public_regeneration.status_code == 404
        regenerated_public = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs/{public_payload['id']}/regenerate",
            headers=member_headers,
        )
        assert regenerated_public.status_code == 200, regenerated_public.text
        regenerated_public_payload = regenerated_public.json()
        assert regenerated_public_payload["status"] == "succeeded"
        assert regenerated_public_payload["inputs"] == public_payload["inputs"]
        assert regenerated_public_payload["outputs"] == public_payload["outputs"]
        assert regenerated_public_payload["regenerated_from_run_id"] == public_payload["id"]
        assert regenerated_public_payload["feedback"] is None
        logical_public_runs = client.get(
            f"/api/v1/public/workflows/{workflow_id}/runs"
            f"?conversation_id={public_payload['conversation_id']}",
            headers=member_headers,
        )
        assert logical_public_runs.status_code == 200, logical_public_runs.text
        assert [item["id"] for item in logical_public_runs.json()["items"]] == [
            regenerated_public_payload["id"]
        ]
        reused_upload = client.post(
            f"/api/v1/public/workflows/{workflow_id}/runs",
            headers=member_headers,
            json={"question": "reuse", "file_ids": [upload_id]},
        )
        assert reused_upload.status_code == 404, reused_upload.text
        assert_upload_cleanup_removes_object(upload_id)
        public_events = client.get(
            f"/api/v1/public/workflows/{workflow_id}/runs/{public_payload['id']}/stream",
            headers=member_headers,
        )
        assert public_events.status_code == 200, public_events.text
        public_event_types = [
            json.loads(line)["type"] for line in public_events.text.splitlines()
        ]
        assert "progress" in public_event_types
        assert public_event_types[-1] == "complete"
        public_conversations = client.get(
            f"/api/v1/public/workflows/{workflow_id}/conversations",
            headers=member_headers,
        )
        assert public_conversations.status_code == 200, public_conversations.text
        assert public_conversations.json()["items"][0]["outputs"] == {
            "result": "public-workflow"
        }

        credential = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}/api-credentials",
            headers=headers,
            json={"name": "Workflow integration"},
        )
        assert credential.status_code == 201, credential.text
        api_headers = {
            "Authorization": f"Bearer {credential.json()['token']}"
        }
        documentation = client.get(
            f"/api/v1/workflow-api/{workflow_id}/documentation",
            headers=api_headers,
        )
        assert documentation.status_code == 200, documentation.text
        assert "inputs" not in documentation.json(), documentation.json()
        api_run = client.post(
            f"/api/v1/workflow-api/{workflow_id}/runs",
            headers=api_headers,
            json={"question": "api-workflow"},
        )
        assert api_run.status_code == 201, api_run.text
        assert api_run.json()["inputs"] == {"question": "api-workflow"}
        assert api_run.json()["outputs"] == {"result": "api-workflow"}
        wrong_api_runtime = client.post(
            f"/api/v1/agent-api/{workflow_id}/runs",
            headers=api_headers,
            json={"goal": "must not run as an agent"},
        )
        assert wrong_api_runtime.status_code == 404, wrong_api_runtime.text


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
    def __init__(self) -> None:
        self.snapshot = SimpleNamespace(
            tool_id="tool-1",
            version_id="version-1",
            function_name="mcp_weather",
            display_name="Weather",
            description="Return weather.",
            input_schema={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
            kind="mcp",
            parallel_safe=False,
            definition_hash="hash-1",
        )
        self.calls: list[tuple[str, str, str, dict]] = []

    def get_by_reference(self, tool_id: str, version_id: str):
        if (tool_id, version_id) != ("tool-1", "version-1"):
            raise ValueError("Workflow Tool snapshot is unavailable.")
        return self.snapshot

    def get_by_function(self, function_name: str):
        return self.snapshot if function_name == self.snapshot.function_name else None

    async def invoke(self, snapshot, node_id, call_id, arguments):
        assert snapshot is self.snapshot
        self.calls.append((node_id, call_id, snapshot.function_name, dict(arguments)))
        return AgentToolResult(
            content="sunny",
            summary="ok",
            output={"weather": "sunny"},
        )


def _llm_scope(**overrides) -> SimpleNamespace:
    scope = SimpleNamespace(
        run=SimpleNamespace(agent_id="workflow-1", model_id="model-1"),
        settings=None,
        models={"model-1": SimpleNamespace(provider_type="openai_compatible")},
        node_histories={},
        tool_runtime=_FakeWorkflowToolRuntime(),
        output_delta=None,
    )
    for key, value in overrides.items():
        setattr(scope, key, value)
    return scope


def _llm_node(config: dict) -> WorkflowNode:
    return WorkflowNode.model_validate(
        {
            "id": "llm-1",
            "position": {"x": 0, "y": 0},
            "data": {"type": "llm", "title": "LLM", "config": config},
        }
    )


def _llm_context(**globals_overrides) -> NodeExecutionContext:
    globals_value = {
        "time": "2026-08-13 10:00:00",
        "history_context": [
            {"question": "q1", "answer": "a1"},
            {"question": "q2", "answer": "a2"},
            {"question": "q3", "answer": "a3"},
        ],
        "chat_id": "conversation-1",
        "start_time": "2026-08-13T10:00:00+00:00",
        **globals_overrides,
    }
    return NodeExecutionContext(
        workflow_inputs={},
        node_outputs={"start": {"question": "hi"}},
        remaining_model_tokens=100,
        globals=globals_value,
    )


def test_workflow_llm_node_dialogue_history_and_params() -> None:
    from unittest.mock import patch

    from app.application.workflow_nodes import execute_workflow_node
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    async def run() -> None:
        fake = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "answer",
                    usage={"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
                )
            ]
        )
        scope = _llm_scope()
        node = _llm_node(
            {
                "prompt": "{{start.question}}",
                "system_prompt": "role",
                "dialogue_number": 2,
                "dialogue_type": "WORKFLOW",
                "model_params_setting": {
                    "temperature": 0.7,
                    "top_p": 0.5,
                    "max_tokens": 1000,
                },
                "model_setting": {"reasoning_content_enable": True},
            }
        )
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=fake,
        ):
            result = await execute_workflow_node(
                scope,
                node,
                _llm_context(),
            )
        messages, kwargs = fake.calls[0]
        assert [type(item).__name__ for item in messages] == [
            "SystemMessage",
            "HumanMessage",
            "AIMessage",
            "HumanMessage",
            "AIMessage",
            "HumanMessage",
        ]
        assert [item.content for item in messages] == [
            "role",
            "q2",
            "a2",
            "q3",
            "a3",
            "hi",
        ]
        # user max_tokens is capped by the remaining budget
        assert kwargs == {"max_tokens": 100, "temperature": 0.7, "top_p": 0.5}
        assert result.outputs == {"text": "answer"}
        assert result.model_tokens == 7
        assert result.inputs["dialogue_type"] == "WORKFLOW"
        assert result.inputs["dialogue_number"] == 2

        # NODE context uses the per-node history map
        fake2 = _FakeLlmModel([_FakeLlmMessage("answer-2")])
        scope2 = _llm_scope(
            node_histories={
                "llm-1": [{"question": "node-q", "answer": "node-a"}]
            }
        )
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=fake2,
        ):
            await execute_workflow_node(
                scope2,
                _llm_node(
                    {
                        "prompt": "now",
                        "dialogue_number": 5,
                        "dialogue_type": "NODE",
                    }
                ),
                _llm_context(),
            )
        messages2, _ = fake2.calls[0]
        assert [item.content for item in messages2] == ["node-q", "node-a", "now"]
        assert all(
            isinstance(item, (HumanMessage, AIMessage)) for item in messages2[:-1]
        )

        # dialogue_number 0 and empty node history bring no history messages
        fake3 = _FakeLlmModel([_FakeLlmMessage("answer-3")])
        scope3 = _llm_scope(node_histories={"llm-1": []})
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=fake3,
        ):
            await execute_workflow_node(
                scope3,
                _llm_node(
                    {
                        "prompt": "now",
                        "dialogue_number": 0,
                        "dialogue_type": "WORKFLOW",
                    }
                ),
                _llm_context(),
            )
        messages3, _ = fake3.calls[0]
        assert len(messages3) == 1
        assert fake3.calls[0][1] == {"max_tokens": 100}

        fake4 = _FakeLlmModel([_FakeLlmMessage("answer-4")])
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=fake4,
        ):
            await execute_workflow_node(
                _llm_scope(),
                _llm_node({"prompt": "now", "dialogue_number": 0}),
                NodeExecutionContext(
                    workflow_inputs={},
                    node_outputs={"start": {"question": "hi"}},
                    remaining_model_tokens=100_000,
                ),
            )
        assert fake4.calls[0][1] == {"max_tokens": 4096}

    asyncio.run(run())


def test_workflow_agent_node_runs_one_durable_pinned_child() -> None:
    from app.application.agent_child_runs import reconcile_workflow_agent_children
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.session import get_session_factory
    from tests.agents import agent_model_server, model_payload

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_base_url, "Child Agent Model"),
        )
        assert model.status_code == 201, model.text
        agent = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=headers,
            json={
                "name": "Pinned child Agent",
                "app_type": "agent",
                "instructions": "Answer the explicit workflow input.",
                "model_id": model.json()["id"],
            },
        )
        assert agent.status_code == 201, agent.text
        agent_id = agent.json()["id"]
        published = client.patch(
            f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}",
            headers=headers,
            json={"published": True},
        )
        assert published.status_code == 200, published.text
        pinned_version_id = published.json()["current_published_version_id"]

        workflow = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=headers,
            json={
                "name": "Agent child Workflow",
                "app_type": "workflow",
                "model_id": model.json()["id"],
            },
        )
        assert workflow.status_code == 201, workflow.text
        workflow_id = workflow.json()["id"]
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{workflow_id}"
        definition = client.get(f"{base}/definition", headers=headers)
        assert definition.status_code == 200, definition.text
        agent_graph = {
            "nodes": [
                {
                    "id": "start",
                    "type": "workflow",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "start", "title": "Start", "config": {}},
                },
                {
                    "id": "child",
                    "type": "workflow",
                    "position": {"x": 220, "y": 0},
                    "data": {
                        "type": "agent",
                        "title": "Pinned Agent",
                        "config": {
                            "agent_id": agent_id,
                            "agent_version_id": pinned_version_id,
                            "input": "{{start.question}}",
                        },
                    },
                },
                {
                    "id": "end",
                    "type": "workflow",
                    "position": {"x": 440, "y": 0},
                    "data": {
                        "type": "end",
                        "title": "End",
                        "config": {"outputs": {"result": "{{child.result}}"}},
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "child"},
                {"id": "e2", "source": "child", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }
        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={
                "expected_revision": definition.json()["revision"],
                "graph": agent_graph,
            },
        )
        assert saved.status_code == 200, saved.text
        version = client.post(f"{base}/publish", headers=headers)
        assert version.status_code == 201, version.text

        republished = client.patch(
            f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}",
            headers=headers,
            json={"instructions": "New draft instructions", "published": True},
        )
        assert republished.status_code == 200, republished.text
        assert republished.json()["current_published_version_id"] != pinned_version_id

        run = client.post(
            f"{base}/runs",
            headers=headers,
            json={
                "source": "published",
                "version_number": version.json()["version_number"],
                "question": "ship this release",
            },
        )
        assert run.status_code == 201, run.text
        assert run.json()["status"] == "succeeded", run.text
        assert run.json()["outputs"] == {"result": "Completed."}
        parent_run_id = run.json()["id"]
        nodes = client.get(f"{base}/runs/{parent_run_id}/nodes", headers=headers)
        assert nodes.status_code == 200, nodes.text
        child_node = next(
            item for item in nodes.json()["items"] if item["node_id"] == "child"
        )
        assert child_node["status"] == "succeeded"
        assert child_node["outputs"]["result"] == "Completed."

    async def assert_lineage() -> None:
        from datetime import datetime, timedelta

        from app.application.agent_child_runs import ensure_workflow_agent_child
        from app.application.agent_runs import cancel_run_tree, prepare_agent_run
        from app.infrastructure.model_utils import utc_now
        from app.infrastructure.repositories import user as user_repository
        from app.shareddomain.agents.models import AGENT_RUN_UNIFIED_RUNNING_STATUS

        async with get_session_factory()() as db:
            children = await agent_repository.list_agent_child_runs(
                db,
                workspace_id,
                parent_run_id,
            )
            assert len(children) == 1
            child = children[0]
            assert child.root_run_id == parent_run_id
            assert child.parent_run_id == parent_run_id
            assert child.parent_node_id == "child"
            assert child.depth == 1
            assert child.agent_publication_version_id == pinned_version_id
            assert child.goal == "ship this release"

            # WF-019: the child inherits the root deadline and the child
            # turn/tool-call budgets, and its model usage merges back to the
            # parent run.
            limits = (child.application_snapshot or {}).get("runtime_limits")
            assert isinstance(limits, dict)
            assert limits.get("max_turns") == 4
            assert limits.get("max_tool_calls") == 6
            assert limits.get("max_model_tokens", 0) >= 1
            deadline = datetime.fromisoformat(limits["deadline_at"])
            assert deadline.tzinfo is not None
            parent = await agent_repository.get_agent_run_by_id(db, parent_run_id)
            assert parent is not None
            assert isinstance(parent.model_usage, dict)
            # The child Agent's model usage is merged back into the parent run.
            assert parent.model_usage.get("model_calls", 0) >= 1

            actor = await user_repository.get_active_user_by_username(db, "admin")
            assert actor is not None
            version = await agent_repository.get_agent_publication_version(
                db,
                workspace_id,
                pinned_version_id,
            )
            assert version is not None
            snapshot = {
                "agent_id": agent_id,
                "version_id": pinned_version_id,
                "configuration_hash": version.configuration_hash,
                "configuration_snapshot": version.configuration_snapshot,
                "resource_snapshot": version.resource_snapshot,
                "bound_by_user_id": actor.id,
            }
            future_deadline = (utc_now() + timedelta(minutes=5)).isoformat()

            # WF-014/WF-017: a duplicate delivery resolves to the persisted
            # child instead of creating a second row, so crash-recovery
            # dispatch can never duplicate the child.
            again = await ensure_workflow_agent_child(
                db,
                parent,
                "child",
                "ship this release",
                snapshot,
                actor,
                "admin",
                deadline_at=future_deadline,
                remaining_model_tokens=1000,
            )
            assert again.id == child.id
            assert len(
                await agent_repository.list_agent_child_runs(
                    db,
                    workspace_id,
                    parent_run_id,
                )
            ) == 1

            # WF-018: a child cannot spawn a nested Agent run.
            try:
                await ensure_workflow_agent_child(
                    db,
                    child,
                    "nested",
                    "nested goal",
                    snapshot,
                    actor,
                    "admin",
                    deadline_at=future_deadline,
                    remaining_model_tokens=1000,
                )
            except ValueError as exc:
                assert "Nested Agent runs are not allowed" in str(exc)
            else:
                raise AssertionError("Nested Agent run was accepted.")
            await db.commit()

            # WF-018: at most MAX_WORKFLOW_CHILDREN children per parent.
            parent_for_limit, _ = await prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "child limit parent",
                actor,
                "admin",
            )
            for node_index in range(1, 5):
                await ensure_workflow_agent_child(
                    db,
                    parent_for_limit,
                    f"limit-node-{node_index}",
                    "limit goal",
                    snapshot,
                    actor,
                    "admin",
                    deadline_at=future_deadline,
                    remaining_model_tokens=1000,
                )
            try:
                await ensure_workflow_agent_child(
                    db,
                    parent_for_limit,
                    "limit-node-5",
                    "limit goal",
                    snapshot,
                    actor,
                    "admin",
                    deadline_at=future_deadline,
                    remaining_model_tokens=1000,
                )
            except ValueError as exc:
                assert "Workflow child Agent limit reached" in str(exc)
            else:
                raise AssertionError("A fifth child was accepted.")
            await db.commit()

            # WF-015/WF-016: a terminal child requeues the awaiting parent
            # exactly once; repeated reconciler scans stay no-ops.
            parent_for_reconcile, _ = await prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "reconcile parent",
                actor,
                "admin",
            )
            parent_for_reconcile.status = AGENT_RUN_UNIFIED_RUNNING_STATUS
            parent_for_reconcile.worker_task_id = "reconcile-worker"
            await agent_repository.save_agent_run(db, parent_for_reconcile)
            await agent_repository.pause_agent_run_for_child(
                db,
                parent_for_reconcile.id,
                "reconcile-worker",
            )
            failed_child = await ensure_workflow_agent_child(
                db,
                parent_for_reconcile,
                "reconcile-node",
                "reconcile goal",
                snapshot,
                actor,
                "admin",
                deadline_at=future_deadline,
                remaining_model_tokens=1000,
            )
            from app.shareddomain.agents.models import AGENT_RUN_FAILED_STATUS

            failed_child.status = AGENT_RUN_FAILED_STATUS
            failed_child.last_error = "boom"
            failed_child.finished_at = utc_now()
            await agent_repository.save_agent_run(db, failed_child)
            await db.commit()
        resumed = await reconcile_workflow_agent_children()
        assert resumed == [parent_for_reconcile.id]
        resumed_again = await reconcile_workflow_agent_children()
        assert resumed_again == []
        async with get_session_factory()() as db:
            requeued = await agent_repository.get_agent_run_by_id(
                db,
                parent_for_reconcile.id,
            )
            assert requeued is not None
            from app.shareddomain.agents.models import agent_run_display_status

            assert agent_run_display_status(requeued.status) == "queued"

            # WF-020: a cancelled parent is never re-woken by its terminal
            # child, and late finalization cannot resurrect it.
            cancelled_parent, _ = await prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "cancelled parent",
                actor,
                "admin",
            )
            cancelled_parent.status = AGENT_RUN_UNIFIED_RUNNING_STATUS
            cancelled_parent.worker_task_id = "cancel-worker"
            await agent_repository.save_agent_run(db, cancelled_parent)
            await agent_repository.pause_agent_run_for_child(
                db,
                cancelled_parent.id,
                "cancel-worker",
            )
            cancelled_child = await ensure_workflow_agent_child(
                db,
                cancelled_parent,
                "cancel-node",
                "cancel goal",
                snapshot,
                actor,
                "admin",
                deadline_at=future_deadline,
                remaining_model_tokens=1000,
            )
            cancelled_child.status = AGENT_RUN_FAILED_STATUS
            cancelled_child.last_error = "cancelled sibling"
            cancelled_child.finished_at = utc_now()
            await agent_repository.save_agent_run(db, cancelled_child)
            await db.commit()
            assert await cancel_run_tree(db, cancelled_parent.id) is True
            await db.commit()
        assert await reconcile_workflow_agent_children() == []
        async with get_session_factory()() as db:
            still_cancelled = await agent_repository.get_agent_run_by_id(
                db,
                cancelled_parent.id,
            )
            assert still_cancelled is not None
            assert still_cancelled.status == "cancelled"

        # ------------------------------------------------------------------
        # preflight_workflow_agent_snapshots / _require_snapshot_binder /
        # ensure_workflow_agent_child failure branches and the expired-parent
        # reconciler path (app/application/agent_child_runs.py). All client
        # interactions for this section were performed synchronously in the
        # test body (ids arrive via the closure: outside_binder_id,
        # member_binder_id, retired_agent_id, retired_version_id,
        # extra_runs).
        # ------------------------------------------------------------------
        from app.application import agent_child_runs as acr
        from app.application import agent_runs as app_agent_runs
        from app.application import workflow_executor
        from app.application.agent_child_runs import (
            _child_goal,
            _fail_expired_waiting_parent,
        )
        from app.application.workflow_executor import run_durable_workflow_run
        from app.entities.agents import AgentPublicationVersion
        from app.infrastructure.model_utils import new_id
        from app.infrastructure.repositories import workflow as workflow_repository
        from app.shareddomain.agents.models import (
            AGENT_RUN_FAILED_STATUS,
            AGENT_RUN_SUCCEEDED_STATUS,
            agent_run_display_status,
        )
        from app.shareddomain.agents.publications import agent_publication_hash
        from app.shareddomain.workflows.engine import WorkflowChildRequired
        from app.shareddomain.workflows.models import WorkflowRunDetail as DetailORM
        from tests.support import settings as make_settings

        runner_settings = make_settings()

        async def pause_run(run_id: str, node_id: str) -> None:
            async with get_session_factory()() as db:
                run = await agent_repository.get_agent_run_by_id(db, run_id)
                assert run is not None
                run.status = AGENT_RUN_UNIFIED_RUNNING_STATUS
                run.worker_task_id = f"worker-{node_id}"
                await agent_repository.save_agent_run(db, run)
                await agent_repository.pause_agent_run_for_child(
                    db,
                    run_id,
                    f"worker-{node_id}",
                )
                await db.commit()

        async def reset_to_running(run_id: str, worker: str) -> None:
            async with get_session_factory()() as db:
                run = await agent_repository.get_agent_run_by_id(db, run_id)
                assert run is not None
                run.status = AGENT_RUN_UNIFIED_RUNNING_STATUS
                run.worker_task_id = worker
                await agent_repository.save_agent_run(db, run)
                await db.commit()

        async with get_session_factory()() as db:
            def make_snapshot(**overrides):
                base = {
                    "agent_id": agent_id,
                    "version_id": pinned_version_id,
                    "configuration_hash": version.configuration_hash,
                    "configuration_snapshot": version.configuration_snapshot,
                    "resource_snapshot": version.resource_snapshot,
                    "bound_by_user_id": actor.id,
                }
                base.update(overrides)
                return base

            # _child_goal (line 41): empty and over-length goals are rejected.
            try:
                _child_goal("   ")
            except ValueError as exc:
                assert "1 to 4000 characters" in str(exc)
            else:
                raise AssertionError("Empty child goal was accepted.")
            try:
                _child_goal("x" * 4001)
            except ValueError as exc:
                assert "1 to 4000 characters" in str(exc)
            else:
                raise AssertionError("Oversized child goal was accepted.")
            assert _child_goal("  ok goal ") == "ok goal"

            # preflight: invalid snapshot shape (87)
            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [{"version_id": 7, "agent_id": None}],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "snapshot is invalid" in str(exc)
            else:
                raise AssertionError("Invalid snapshot shape was accepted.")

            # preflight: unknown publication version (93-105)
            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [make_snapshot(version_id=new_id())],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "publication changed or is invalid" in str(exc)
            else:
                raise AssertionError("Unknown publication version was accepted.")

            # preflight: stale configuration hash (93-105)
            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [make_snapshot(configuration_hash="stale-hash")],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "publication changed or is invalid" in str(exc)
            else:
                raise AssertionError("Stale configuration hash was accepted.")

            # preflight happy path (93-107, 108-128 with an empty tool list)
            await acr.preflight_workflow_agent_snapshots(
                db,
                workspace_id,
                [snapshot],
                execution_user_id=actor.id,
                access_source="console",
            )

            # binder branches (52, 55, 58-59, 71-72)
            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [make_snapshot(bound_by_user_id=None)],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "binder is missing" in str(exc)
            else:
                raise AssertionError("Missing binder was accepted.")

            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [make_snapshot(bound_by_user_id="ghost-user")],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "binder is unavailable" in str(exc)
            else:
                raise AssertionError("Unknown binder was accepted.")

            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [make_snapshot(bound_by_user_id=outside_binder_id)],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "binder is unavailable" in str(exc)
            else:
                raise AssertionError("Non-member binder was accepted.")

            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [make_snapshot(bound_by_user_id=member_binder_id)],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "access was revoked" in str(exc)
            else:
                raise AssertionError(
                    "Member binder without view access was accepted."
                )

            # unavailable target agent (68): an agent that was published and
            # then unpublished (created synchronously in the test body).
            version2 = await agent_repository.get_agent_publication_version(
                db,
                workspace_id,
                retired_version_id,
            )
            assert version2 is not None
            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [
                        make_snapshot(
                            agent_id=retired_agent_id,
                            version_id=retired_version_id,
                            configuration_hash=version2.configuration_hash,
                            configuration_snapshot=version2.configuration_snapshot,
                            resource_snapshot=version2.resource_snapshot,
                        )
                    ],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "Workflow Agent is unavailable" in str(exc)
            else:
                raise AssertionError("Unpublished agent snapshot was accepted.")

            # tool payload branches (112-113, 118, 119-128): craft immutable
            # publication rows whose resource snapshots carry tool payloads.
            tool_payload = {
                "schema_version": 1,
                "tool_id": "ghost-tool",
                "version_id": "ghost-version",
                "source_id": "ghost-source",
                "kind": "mcp",
                "function_name": "mcp_lookup",
                "display_name": "Lookup",
                "description": "",
                "input_schema": {},
                "output_schema": None,
                "definition_hash": "def-hash",
                "policy_id": "policy-1",
                "policy_revision": 1,
                "bound_by_user_id": actor.id,
                "approval": "each_call",
                "effect": "unknown",
                "allowed_access_sources": ["console"],
                "workflow_callable": False,
                "parallel_safe": False,
                "execution_spec": {"server_id": "srv", "tool_name": "lookup"},
            }

            async def craft_version(
                version_number: int,
                tools: list,
            ) -> AgentPublicationVersion:
                crafted = AgentPublicationVersion(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    version_number=version_number,
                    configuration_snapshot=version.configuration_snapshot,
                    resource_snapshot={
                        "schema_version": 1,
                        "knowledge_base_ids": [],
                        "tools": tools,
                        "agents": [],
                    },
                    published_by_user_id=actor.id,
                )
                crafted.configuration_hash = agent_publication_hash(
                    crafted.configuration_snapshot,
                    crafted.resource_snapshot,
                )
                crafted = await agent_repository.create_agent_publication_version(
                    db,
                    crafted,
                )
                await db.commit()
                return crafted

            invalid_tools_version = await craft_version(10, [{"nope": 1}])
            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [
                        make_snapshot(
                            version_id=invalid_tools_version.id,
                            configuration_hash=(
                                invalid_tools_version.configuration_hash
                            ),
                            configuration_snapshot=(
                                invalid_tools_version.configuration_snapshot
                            ),
                            resource_snapshot=(
                                invalid_tools_version.resource_snapshot
                            ),
                        )
                    ],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "Tool snapshot is invalid" in str(exc)
            else:
                raise AssertionError("Invalid tool snapshot was accepted.")

            for malformed_resource_snapshot in (None, {"tools": None}):
                malformed_hash = agent_publication_hash(
                    version.configuration_snapshot,
                    malformed_resource_snapshot,
                )
                malformed_version_id = new_id()
                with patch.object(
                    acr.agent_repository,
                    "get_agent_publication_version",
                    return_value=SimpleNamespace(
                        agent_id=agent_id,
                        configuration_hash=malformed_hash,
                        configuration_snapshot=version.configuration_snapshot,
                        resource_snapshot=malformed_resource_snapshot,
                    ),
                ):
                    try:
                        await acr.preflight_workflow_agent_snapshots(
                            db,
                            workspace_id,
                            [
                                make_snapshot(
                                    version_id=malformed_version_id,
                                    configuration_hash=malformed_hash,
                                    resource_snapshot=malformed_resource_snapshot,
                                )
                            ],
                            execution_user_id=actor.id,
                            access_source="console",
                        )
                    except ValueError as exc:
                        assert str(exc) == "Workflow Agent Tool snapshot is invalid."
                    else:
                        raise AssertionError(
                            "Malformed Tool snapshot container was accepted."
                        )

            each_call_version = await craft_version(11, [tool_payload])
            each_call_snapshot = make_snapshot(
                version_id=each_call_version.id,
                configuration_hash=each_call_version.configuration_hash,
                configuration_snapshot=each_call_version.configuration_snapshot,
                resource_snapshot=each_call_version.resource_snapshot,
            )
            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [each_call_snapshot],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "must be automatic and read-only" in str(exc)
            else:
                raise AssertionError("Write tool was accepted for a child.")

            auto_tool_payload = {
                **tool_payload,
                "approval": "auto",
                "effect": "external_read",
                "allowed_access_sources": ["console", "public", "api"],
                "workflow_callable": True,
                "parallel_safe": True,
            }
            revoked_version = await craft_version(12, [auto_tool_payload])
            try:
                await acr.preflight_workflow_agent_snapshots(
                    db,
                    workspace_id,
                    [
                        make_snapshot(
                            version_id=revoked_version.id,
                            configuration_hash=revoked_version.configuration_hash,
                            configuration_snapshot=(
                                revoked_version.configuration_snapshot
                            ),
                            resource_snapshot=revoked_version.resource_snapshot,
                        )
                    ],
                    execution_user_id=actor.id,
                    access_source="console",
                )
            except ValueError as exc:
                assert "Tool access was revoked" in str(exc)
            else:
                raise AssertionError("Revoked tool access was accepted.")

            # ensure_workflow_agent_child branches (165, 183, 190-191, 196, 41)
            branch_parent, _ = await prepare_agent_run(
                db,
                workspace_id,
                agent_id,
                "branch parent",
                actor,
                "admin",
            )
            try:
                await ensure_workflow_agent_child(
                    db,
                    branch_parent,
                    "branch-budget",
                    "goal",
                    snapshot,
                    actor,
                    "admin",
                    deadline_at=future_deadline,
                    remaining_model_tokens=0,
                )
            except ValueError as exc:
                assert "token budget exhausted" in str(exc)
            else:
                raise AssertionError("Exhausted child token budget was accepted.")
            try:
                await ensure_workflow_agent_child(
                    db,
                    branch_parent,
                    "branch-invalid",
                    "goal",
                    {"version_id": None, "agent_id": agent_id},
                    actor,
                    "admin",
                    deadline_at=future_deadline,
                    remaining_model_tokens=10,
                )
            except ValueError as exc:
                assert "snapshot is invalid" in str(exc)
            else:
                raise AssertionError("Invalid ensure snapshot was accepted.")

            try:
                await ensure_workflow_agent_child(
                    db,
                    branch_parent,
                    "branch-stale",
                    "goal",
                    make_snapshot(configuration_hash="stale-hash"),
                    actor,
                    "admin",
                    deadline_at=future_deadline,
                    remaining_model_tokens=10,
                )
            except ValueError as exc:
                assert "publication changed or is invalid" in str(exc)
            else:
                raise AssertionError("Stale ensure snapshot was accepted.")

            try:
                await ensure_workflow_agent_child(
                    db,
                    branch_parent,
                    "branch-tools",
                    "goal",
                    make_snapshot(
                        version_id=invalid_tools_version.id,
                        configuration_hash=invalid_tools_version.configuration_hash,
                        configuration_snapshot=(
                            invalid_tools_version.configuration_snapshot
                        ),
                        resource_snapshot=(
                            invalid_tools_version.resource_snapshot
                        ),
                    ),
                    actor,
                    "admin",
                    deadline_at=future_deadline,
                    remaining_model_tokens=10,
                )
            except ValueError as exc:
                assert "Tool snapshot is invalid" in str(exc)
            else:
                raise AssertionError("Invalid ensure tool snapshot was accepted.")

            try:
                await ensure_workflow_agent_child(
                    db,
                    branch_parent,
                    "branch-write",
                    "goal",
                    each_call_snapshot,
                    actor,
                    "admin",
                    deadline_at=future_deadline,
                    remaining_model_tokens=10,
                )
            except ValueError as exc:
                assert "must be automatic and read-only" in str(exc)
            else:
                raise AssertionError("Write tool ensure snapshot was accepted.")

            try:
                await ensure_workflow_agent_child(
                    db,
                    branch_parent,
                    "branch-empty-goal",
                    "",
                    snapshot,
                    actor,
                    "admin",
                    deadline_at=future_deadline,
                    remaining_model_tokens=10,
                )
            except ValueError as exc:
                assert "1 to 4000 characters" in str(exc)
            else:
                raise AssertionError("Empty ensure goal was accepted.")
            await db.commit()

            # _fail_expired_waiting_parent (236-241) against a real workflow
            # run with a persisted WorkflowRunDetail.
            expiry_parent_id = extra_runs["expiry"]
            await pause_run(expiry_parent_id, "expiry-node")
            expiry_parent = await agent_repository.get_agent_run_by_id(
                db,
                expiry_parent_id,
            )
            assert expiry_parent is not None
            detail = await workflow_repository.get_run_detail(db, expiry_parent_id)
            assert detail is not None
            detail_row = await db.get(DetailORM, detail.id)
            assert detail_row is not None
            # future deadline -> not expired (239-240)
            detail_row.deadline_at = utc_now() + timedelta(hours=1)
            await db.commit()
            assert await _fail_expired_waiting_parent(db, expiry_parent) is False
            # naive deadline is normalized to UTC (237-238), still future
            detail_row.deadline_at = (utc_now() + timedelta(hours=1)).replace(
                tzinfo=None
            )
            await db.commit()
            assert await _fail_expired_waiting_parent(db, expiry_parent) is False
            # expired deadline fails the waiting parent (236, 241)
            detail_row.deadline_at = utc_now() - timedelta(hours=1)
            await db.commit()
            assert await _fail_expired_waiting_parent(db, expiry_parent) is True
            expired = await agent_repository.get_agent_run_by_id(
                db,
                expiry_parent_id,
            )
            assert expired is not None
            assert expired.status == AGENT_RUN_FAILED_STATUS
            assert "deadline exceeded" in (expired.last_error or "")

        # reconcile_workflow_agent_children child_run_id branches
        # (262, 273, 279, 281)
        assert await reconcile_workflow_agent_children(
            child_run_id="missing-child-id"
        ) == []
        async with get_session_factory()() as db:
            limit_children = await agent_repository.list_agent_child_runs(
                db,
                workspace_id,
                parent_for_limit.id,
            )
            assert limit_children
        assert await reconcile_workflow_agent_children(
            child_run_id=limit_children[0].id
        ) == []  # non-terminal child skipped (273)
        assert await reconcile_workflow_agent_children(
            child_run_id=failed_child.id
        ) == []  # parent no longer awaiting (279)
        expired_child_parent = extra_runs["expiry-reconcile"]
        await pause_run(expired_child_parent, "expiry-reconcile-node")
        async with get_session_factory()() as db:
            expired_child_parent_run = await agent_repository.get_agent_run_by_id(
                db,
                expired_child_parent,
            )
            assert expired_child_parent_run is not None
            expire_child = await ensure_workflow_agent_child(
                db,
                expired_child_parent_run,
                "expiry-reconcile-node",
                "expiry goal",
                snapshot,
                actor,
                "admin",
                deadline_at=future_deadline,
                remaining_model_tokens=10,
            )
            expire_child.status = AGENT_RUN_FAILED_STATUS
            expire_child.last_error = "expired sibling"
            expire_child.finished_at = utc_now()
            await agent_repository.save_agent_run(db, expire_child)
            detail = await workflow_repository.get_run_detail(
                db,
                expired_child_parent,
            )
            assert detail is not None
            detail_row = await db.get(DetailORM, detail.id)
            assert detail_row is not None
            detail_row.deadline_at = utc_now() - timedelta(hours=1)
            await db.commit()
        assert await reconcile_workflow_agent_children(
            child_run_id=expire_child.id
        ) == []  # expired parent failed instead of resuming (281)
        async with get_session_factory()() as db:
            expired_parent_after = await agent_repository.get_agent_run_by_id(
                db,
                expired_child_parent,
            )
            assert expired_parent_after is not None
            assert expired_parent_after.status == AGENT_RUN_FAILED_STATUS

        # ------------------------------------------------------------------
        # workflow_executor child-request recovery paths via DIRECT
        # execution (coverage only records non-request code).
        # ------------------------------------------------------------------
        original_maintain = workflow_executor.maintain_agent_run_lease

        async def noop_maintain(run_id, worker_task_id, settings, lease_lost):
            return None

        workflow_executor.maintain_agent_run_lease = noop_maintain
        original_run_enqueue = app_agent_runs.enqueue_prepared_agent_run
        enqueued_children: list[str] = []

        async def record_enqueue(run_id, _settings, **_kwargs) -> None:
            enqueued_children.append(run_id)

        try:
            # Scenario A: the child was persisted by ensure, but the engine
            # never saw the pending-child bookkeeping (simulated by raising
            # WorkflowChildRequired from ensure); the fallback child lookup
            # (572-579) finds the row and enqueues it (584-585).
            real_ensure = workflow_executor.ensure_workflow_agent_child

            async def ensure_then_raise(
                db,
                parent,
                parent_node_id,
                input_value,
                snapshot,
                actor,
                workspace_role,
                **kwargs,
            ):
                child = await real_ensure(
                    db,
                    parent,
                    parent_node_id,
                    input_value,
                    snapshot,
                    actor,
                    workspace_role,
                    **kwargs,
                )
                await db.commit()
                raise WorkflowChildRequired({"runtime_node_id": parent_node_id})

            fallback_run_id = extra_runs["fallback"]
            await reset_to_running(fallback_run_id, "worker-child-a")
            workflow_executor.ensure_workflow_agent_child = ensure_then_raise
            app_agent_runs.enqueue_prepared_agent_run = record_enqueue
            try:
                outcome = await run_durable_workflow_run(
                    fallback_run_id,
                    runner_settings,
                    worker_task_id="worker-child-a",
                    generation="unified",
                )
            finally:
                workflow_executor.ensure_workflow_agent_child = real_ensure
                app_agent_runs.enqueue_prepared_agent_run = original_run_enqueue
            assert outcome == "finished"
            if len(enqueued_children) != 1:
                async with get_session_factory()() as db:
                    diag = await agent_repository.get_agent_run_by_id(
                        db,
                        fallback_run_id,
                    )
                raise AssertionError(
                    f"scenario A enqueue mismatch: enqueued={enqueued_children!r} "
                    f"run_status={diag.status if diag else None} "
                    f"last_error={diag.last_error if diag else None}"
                )
            assert len(enqueued_children) == 1
            async with get_session_factory()() as db:
                fallback_children = await agent_repository.list_agent_child_runs(
                    db,
                    workspace_id,
                    fallback_run_id,
                )
                assert len(fallback_children) == 1

            # Scenario B: no child row exists -> 581 error and the run fails.
            async def ensure_raises(
                db,
                parent,
                parent_node_id,
                input_value,
                snapshot,
                actor,
                workspace_role,
                **kwargs,
            ):
                raise WorkflowChildRequired({"runtime_node_id": parent_node_id})

            missing_run_id = extra_runs["missing"]
            await reset_to_running(missing_run_id, "worker-child-b")
            workflow_executor.ensure_workflow_agent_child = ensure_raises
            try:
                outcome = await run_durable_workflow_run(
                    missing_run_id,
                    runner_settings,
                    worker_task_id="worker-child-b",
                    generation="unified",
                )
            finally:
                workflow_executor.ensure_workflow_agent_child = real_ensure
            assert outcome == "finished"
            async with get_session_factory()() as db:
                missing_run = await agent_repository.get_agent_run_by_id(
                    db,
                    missing_run_id,
                )
                assert missing_run is not None
                assert missing_run.status == AGENT_RUN_FAILED_STATUS
                assert "child was not persisted" in (missing_run.last_error or "")

            # Scenario C: pause-for-child loses the lease -> 530-532.
            real_pause = agent_repository.pause_agent_run_for_child

            async def false_pause(db, run_id, worker_task_id):
                return False

            lease_run_id = extra_runs["lease"]
            await reset_to_running(lease_run_id, "worker-child-c")
            agent_repository.pause_agent_run_for_child = false_pause
            try:
                outcome = await run_durable_workflow_run(
                    lease_run_id,
                    runner_settings,
                    worker_task_id="worker-child-c",
                    generation="unified",
                )
            finally:
                agent_repository.pause_agent_run_for_child = real_pause
            assert outcome == "finished"
            async with get_session_factory()() as db:
                lease_run = await agent_repository.get_agent_run_by_id(
                    db,
                    lease_run_id,
                )
                assert lease_run is not None
                assert lease_run.status == AGENT_RUN_FAILED_STATUS
                assert "lease was lost" in (lease_run.last_error or "")

            # Scenario D: the real child-request path (485-486, 524-529,
            # 568-571, 584-585): the child is persisted, paused for, and
            # enqueued. The enqueue is recorded (not executed) so the child
            # never needs a live provider.
            real_run_id = extra_runs["real"]
            await reset_to_running(real_run_id, "worker-child-d")
            enqueued_children.clear()
            app_agent_runs.enqueue_prepared_agent_run = record_enqueue
            try:
                outcome = await run_durable_workflow_run(
                    real_run_id,
                    runner_settings,
                    worker_task_id="worker-child-d",
                    generation="unified",
                )
            finally:
                app_agent_runs.enqueue_prepared_agent_run = original_run_enqueue
            assert outcome == "finished"
            async with get_session_factory()() as db:
                real_children = await agent_repository.list_agent_child_runs(
                    db,
                    workspace_id,
                    real_run_id,
                )
                assert len(real_children) == 1
                real_child_id = real_children[0].id
                assert enqueued_children == [real_child_id]
                real_parent = await agent_repository.get_agent_run_by_id(
                    db,
                    real_run_id,
                )
                assert real_parent is not None
                assert (
                    agent_run_display_status(real_parent.status)
                    == "awaiting_child"
                )
        finally:
            workflow_executor.maintain_agent_run_lease = original_maintain
            app_agent_runs.enqueue_prepared_agent_run = original_run_enqueue

        # Tidy up leftover active runs so later suites never observe them.
        async with get_session_factory()() as db:
            for leftover in (
                fallback_run_id,
                real_run_id,
                branch_parent.id,
            ):
                await cancel_run_tree(db, leftover)
            await db.commit()

    # Synchronous setup for the coverage additions: client calls cannot run
    # inside the async lineage block after an eager workflow run (stale
    # loop-bound state, including the login rate-limit redis singleton), so
    # the binder users, the retired agent, and the extra runs are prepared
    # here and consumed via the closure.
    from unittest.mock import AsyncMock, patch

    async def create_direct_user(username: str, member: bool) -> str:
        from app.entities.user import User
        from app.entities.workspace import WorkspaceMembership
        from app.infrastructure.repositories import user as user_repository

        async with get_session_factory()() as db:
            user = await user_repository.create_user(
                db,
                User(
                    username=username,
                    email=f"{username}@example.com",
                    name=username,
                    password_hash="unused-hash",
                    must_change_password=False,
                    is_active=True,
                ),
            )
            if member:
                await user_repository.create_workspace_membership(
                    db,
                    WorkspaceMembership(
                        workspace_id=workspace_id,
                        user_id=user.id,
                        role="member",
                    ),
                )
            await db.commit()
            return user.id

    outside_binder_id = asyncio.run(
        create_direct_user("child-outside-binder", member=False)
    )
    member_binder_id = asyncio.run(
        create_direct_user("child-member-binder", member=True)
    )

    retired_agent = client.post(
        f"/api/v1/workspaces/{workspace_id}/agents",
        headers=headers,
        json={
            "name": "Retired child Agent",
            "app_type": "agent",
            "instructions": "x",
            "model_id": model.json()["id"],
        },
    )
    assert retired_agent.status_code == 201, retired_agent.text
    retired_agent_id = retired_agent.json()["id"]
    retired_publish = client.patch(
        f"/api/v1/workspaces/{workspace_id}/agents/{retired_agent_id}",
        headers=headers,
        json={"published": True},
    )
    assert retired_publish.status_code == 200, retired_publish.text
    retired_version_id = retired_publish.json()["current_published_version_id"]
    retired_unpublish = client.patch(
        f"/api/v1/workspaces/{workspace_id}/agents/{retired_agent_id}",
        headers=headers,
        json={"published": False},
    )
    assert retired_unpublish.status_code == 200, retired_unpublish.text

    extra_runs = {}
    with patch("app.application.workflow_runs.enqueue_agent_run", new=AsyncMock()):
        for key, question in (
            ("expiry", "expiry parent"),
            ("expiry-reconcile", "expiry reconcile parent"),
            ("fallback", "child fallback parent"),
            ("missing", "child missing parent"),
            ("lease", "child lease parent"),
            ("real", "child real parent"),
        ):
            created = client.post(
                f"{base}/runs",
                headers=headers,
                json={"source": "draft", "question": question},
            )
            assert created.status_code == 201, created.text
            extra_runs[key] = created.json()["id"]

    asyncio.run(assert_lineage())


def test_workflow_llm_node_reasoning_and_mcp_tool_loop() -> None:
    from unittest.mock import patch

    from app.application.workflow_nodes import execute_workflow_node
    from langchain_core.messages import ToolMessage
    from app.schemas.workflow import LlmNodeConfig

    async def run() -> None:
        assert LlmNodeConfig.model_validate({"prompt": "x"}).is_result is True
        assert (
            LlmNodeConfig.model_validate(
                {"prompt": "x", "mcp_servers": [{"server_id": "s-1", "tool_name": "t"}]}
            ).mcp_servers[0].tool_name
            == "t"
        )
        fake = _FakeLlmModel(
            [
                _FakeLlmMessage(
                    "",
                    tool_calls=[
                        {"id": "call-1", "name": "mcp_weather", "args": {"city": "sh"}}
                    ],
                    usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                ),
                _FakeLlmMessage(
                    "final answer",
                    usage={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
                    additional_kwargs={"reasoning_content": "thinking..."},
                ),
            ]
        )
        runtime = _FakeWorkflowToolRuntime()
        scope = _llm_scope(tool_runtime=runtime)
        node = _llm_node(
            {
                "prompt": "hello",
                "tools": [{"tool_id": "tool-1", "version_id": "version-1"}],
                "model_setting": {"reasoning_content_enable": True},
            }
        )
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=fake,
        ):
            result = await execute_workflow_node(scope, node, _llm_context())
        assert result.outputs["text"] == "final answer"
        assert result.outputs["reasoning_content"] == "thinking..."
        assert result.model_tokens == 35
        assert runtime.calls == [
            ("llm-1", "llm:0:mcp_weather", "mcp_weather", {"city": "sh"}),
        ]
        assert [tool.name for tool in fake.bound_tools] == ["mcp_weather"]
        # the second model call carries the tool result
        second_messages = fake.calls[1][0]
        tool_messages = [
            item for item in second_messages if isinstance(item, ToolMessage)
        ]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "call-1"
        assert tool_messages[0].content == "sunny"

        # A canonical reference without a frozen snapshot fails the node.
        scope2 = _llm_scope()
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=_FakeLlmModel([_FakeLlmMessage("x")]),
        ):
            try:
                await execute_workflow_node(
                    scope2,
                    _llm_node(
                        {
                            "prompt": "hello",
                            "tools": [
                                {"tool_id": "missing", "version_id": "version-1"}
                            ],
                        }
                    ),
                    _llm_context(),
                )
            except ValueError as exc:
                assert "snapshot is unavailable" in str(exc)
            else:
                raise AssertionError("unbound Workflow Tool was accepted")

    asyncio.run(run())


def test_workflow_llm_result_streams_markdown_deltas() -> None:
    from unittest.mock import patch

    from app.application.workflow_nodes import execute_workflow_node
    from langchain_core.messages import AIMessageChunk

    class StreamingModel(_FakeLlmModel):
        async def astream(self, messages, **kwargs):
            self.calls.append((list(messages), dict(kwargs)))
            yield AIMessageChunk(content="# 标题")
            yield AIMessageChunk(content="\n\n正文")

    async def run() -> None:
        deltas: list[tuple[str, str]] = []

        async def emit(node_id: str, delta: str) -> None:
            deltas.append((node_id, delta))

        model = StreamingModel([_FakeLlmMessage("fallback")])
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=model,
        ):
            result = await execute_workflow_node(
                _llm_scope(output_delta=emit),
                _llm_node({"prompt": "用 Markdown 回答"}),
                _llm_context(),
            )

        assert deltas == [("llm-1", "# 标题"), ("llm-1", "\n\n正文")]
        assert result.outputs == {"text": "# 标题\n\n正文"}

        hidden = StreamingModel([_FakeLlmMessage("内部结果")])
        with patch(
            "app.application.workflow_nodes.build_chat_model",
            return_value=hidden,
        ):
            await execute_workflow_node(
                _llm_scope(output_delta=emit),
                _llm_node(
                    {"prompt": "优化问题", "is_result": False}
                ),
                _llm_context(),
            )
        assert deltas == [("llm-1", "# 标题"), ("llm-1", "\n\n正文")]

    asyncio.run(run())


def test_cancelling_queued_workflow_run_is_idempotent() -> None:
    from unittest.mock import AsyncMock, patch

    from tests.agents import agent_model_server, model_payload

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_base_url, "Cancel Workflow Model"),
        )
        assert model.status_code == 201, model.text
        workflow = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=headers,
            json={
                "name": "Cancelable Workflow",
                "app_type": "workflow",
                "model_id": model.json()["id"],
            },
        )
        assert workflow.status_code == 201, workflow.text
        base = (
            f"/api/v1/workspaces/{workspace_id}/workflows/"
            f"{workflow.json()['id']}"
        )
        definition = client.get(f"{base}/definition", headers=headers)
        assert definition.status_code == 200, definition.text
        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={
                "expected_revision": definition.json()["revision"],
                "graph": graph(),
            },
        )
        assert saved.status_code == 200, saved.text
        with patch(
            "app.application.workflow_runs.enqueue_agent_run",
            new=AsyncMock(),
        ):
            run = client.post(
                f"{base}/runs",
                headers=headers,
                json={"source": "draft", "question": "cancel me"},
            )
        assert run.status_code == 201, run.text
        run_id = run.json()["id"]
        cancelled = client.post(f"{base}/runs/{run_id}/cancel", headers=headers)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        repeated = client.post(f"{base}/runs/{run_id}/cancel", headers=headers)
        assert repeated.status_code == 409, repeated.text


def test_workflow_executor_recovery_paths() -> None:
    """Direct-execution recovery branches of workflow_executor.py.

    Runs are created through the API with the queue dispatch suppressed and
    then executed by calling ``run_durable_workflow_run`` directly, because
    coverage only records code reached outside request handling.
    """
    from unittest.mock import AsyncMock, patch

    from tests.agents import agent_model_server, model_payload
    from tests.support import settings as make_settings

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_base_url, "Recovery Workflow Model"),
        )
        assert model.status_code == 201, model.text
        model_id = model.json()["id"]

        def make_workflow(name: str, workflow_graph: dict) -> tuple[str, str]:
            created = client.post(
                f"/api/v1/workspaces/{workspace_id}/agents",
                headers=headers,
                json={
                    "name": name,
                    "app_type": "workflow",
                    "model_id": model_id,
                },
            )
            assert created.status_code == 201, created.text
            agent_id = created.json()["id"]
            base = f"/api/v1/workspaces/{workspace_id}/workflows/{agent_id}"
            definition = client.get(f"{base}/definition", headers=headers)
            assert definition.status_code == 200, definition.text
            saved = client.put(
                f"{base}/definition",
                headers=headers,
                json={
                    "expected_revision": definition.json()["revision"],
                    "graph": workflow_graph,
                },
            )
            assert saved.status_code == 200, saved.text
            version = client.post(f"{base}/publish", headers=headers)
            assert version.status_code == 201, version.text
            return agent_id, base

        simple_base = make_workflow(
            "Simple Recovery Workflow",
            graph(),
        )[1]
        form_graph = {
            "nodes": [
                {
                    "id": "start",
                    "type": "workflow",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "start", "title": "Start", "config": {}},
                },
                {
                    "id": "form",
                    "type": "workflow",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "type": "form-node",
                        "title": "Form",
                        "config": {
                            "form_field_list": [
                                {
                                    "variable": "name",
                                    "name": "Name",
                                    "type": "input",
                                }
                            ],
                            "form_content_format": "Please fill: {{ form }}",
                        },
                    },
                },
                {
                    "id": "end",
                    "type": "workflow",
                    "position": {"x": 400, "y": 0},
                    "data": {
                        "type": "end",
                        "title": "End",
                        "config": {"outputs": {"result": "done"}},
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "form"},
                {"id": "e2", "source": "form", "target": "end"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }
        form_base = make_workflow("Form Recovery Workflow", form_graph)[1]

        def create_run(base: str, question: str) -> str:
            with patch(
                "app.application.workflow_runs.enqueue_agent_run",
                new=AsyncMock(),
            ):
                created = client.post(
                    f"{base}/runs",
                    headers=headers,
                    json={"source": "published", "question": question},
                )
            assert created.status_code == 201, created.text
            return created.json()["id"]

        async def run_scenarios() -> None:
            from app.application import workflow_executor
            from app.application.workflow_executor import run_durable_workflow_run
            from app.infrastructure.model_utils import utc_now
            from app.infrastructure.repositories import agent as agent_repository
            from app.infrastructure.repositories import workflow as workflow_repository
            from app.infrastructure.session import get_session_factory
            from app.shareddomain.agents.models import (
                AGENT_RUN_FAILED_STATUS,
                agent_run_display_status,
            )
            from app.shareddomain.workflows.models import (
                WorkflowRunDetail as DetailORM,
            )

            runner_settings = make_settings()
            original_maintain = workflow_executor.maintain_agent_run_lease

            async def noop_maintain(run_id, worker_task_id, settings, lease_lost):
                return None

            workflow_executor.maintain_agent_run_lease = noop_maintain
            try:
                # 1) form node without a submission pauses the run for input
                # (WorkflowInputRequired branch, 552-566).
                form_run_id = create_run(form_base, "fill the form")
                outcome = await run_durable_workflow_run(
                    form_run_id,
                    runner_settings,
                    worker_task_id="worker-input-required",
                    generation="unified",
                )
                assert outcome == "finished"
                async with get_session_factory()() as db:
                    paused = await agent_repository.get_agent_run_by_id(
                        db,
                        form_run_id,
                    )
                    assert paused is not None
                    assert (
                        agent_run_display_status(paused.status)
                        == "awaiting_input"
                    )
                    events = await agent_repository.list_agent_run_events(
                        db,
                        form_run_id,
                    )
                    assert any(
                        event.event.get("type") == "workflow_input_required"
                        for event in events
                    )

                # 2) a corrupted resource snapshot fails the run during
                # scope loading (192) and drives the failure finalizer
                # (660-675, 698).
                snapshot_run_id = create_run(simple_base, "corrupt snapshot")
                async with get_session_factory()() as db:
                    detail = await workflow_repository.get_run_detail(
                        db,
                        snapshot_run_id,
                    )
                    assert detail is not None
                    detail_row = await db.get(DetailORM, detail.id)
                    assert detail_row is not None
                    detail_row.resource_snapshot = {
                        **detail_row.resource_snapshot,
                        "schema_version": 99,
                    }
                    await db.commit()
                outcome = await run_durable_workflow_run(
                    snapshot_run_id,
                    runner_settings,
                    worker_task_id="worker-invalid-snapshot",
                    generation="unified",
                )
                assert outcome == "finished"
                async with get_session_factory()() as db:
                    failed = await agent_repository.get_agent_run_by_id(
                        db,
                        snapshot_run_id,
                    )
                    assert failed is not None
                    assert failed.status == AGENT_RUN_FAILED_STATUS
                    assert (
                        failed.last_error
                        == "Workflow resource snapshot is invalid."
                    )

                # 3) an oversized node output fails the run through the
                # node-error mapping (586-590) and the failure finalizer.
                huge_run_id = create_run(simple_base, "huge output")
                original_execute = workflow_executor.execute_workflow_node

                async def huge_output(scope, node, context):
                    from app.shareddomain.workflows.engine import NodeResult

                    return NodeResult(
                        outputs={"result": "x" * 300000},
                        model_tokens=1,
                    )

                workflow_executor.execute_workflow_node = huge_output
                try:
                    outcome = await run_durable_workflow_run(
                        huge_run_id,
                        runner_settings,
                        worker_task_id="worker-huge-output",
                        generation="unified",
                    )
                finally:
                    workflow_executor.execute_workflow_node = original_execute
                assert outcome == "finished"
                async with get_session_factory()() as db:
                    huge_failed = await agent_repository.get_agent_run_by_id(
                        db,
                        huge_run_id,
                    )
                    assert huge_failed is not None
                    assert huge_failed.status == AGENT_RUN_FAILED_STATUS
                    if "256 KiB" not in (huge_failed.last_error or ""):
                        raise AssertionError(
                            f"huge output last_error={huge_failed.last_error!r}"
                        )
                    assert "256 KiB" in (huge_failed.last_error or "")

                # 4) a legacy-generation claim marks expired tool calls (728)
                # and completes the run.
                legacy_run_id = create_run(simple_base, "legacy claim")
                async with get_session_factory()() as db:
                    legacy = await agent_repository.get_agent_run_by_id(
                        db,
                        legacy_run_id,
                    )
                    assert legacy is not None
                    legacy.status = "queued"
                    legacy.configuration_source = "legacy"
                    await agent_repository.save_agent_run(db, legacy)
                    await db.commit()
                outcome = await run_durable_workflow_run(
                    legacy_run_id,
                    runner_settings,
                    worker_task_id="worker-legacy-claim",
                    generation="legacy",
                )
                assert outcome == "finished"
                async with get_session_factory()() as db:
                    legacy_done = await agent_repository.get_agent_run_by_id(
                        db,
                        legacy_run_id,
                    )
                    assert legacy_done is not None
                    assert legacy_done.status == "succeeded"
            finally:
                workflow_executor.maintain_agent_run_lease = original_maintain
                async with get_session_factory()() as db:
                    for leftover in (
                        form_run_id,
                        snapshot_run_id,
                        huge_run_id,
                        legacy_run_id,
                    ):
                        await agent_repository.cancel_agent_run_tree(
                            db,
                            leftover,
                            utc_now(),
                        )
                    await db.commit()

        asyncio.run(run_scenarios())


def main() -> None:
    test_default_workflow_only_contains_start()
    test_workflow_interaction_config_rejects_audio_uploads()
    test_workflow_validation_rejects_cycles_and_downstream_references()
    test_workflow_engine_runs_branch_and_join_deterministically()
    test_condition_node_selects_the_first_matching_branch_or_else()
    test_workflow_engine_returns_enabled_llm_content()
    test_workflow_reply_node_modes_and_result_output()
    test_workflow_engine_enforces_step_and_token_budgets()
    test_workflow_model_output_limit_uses_provider_native_argument()
    test_workflow_resources_come_from_nodes_without_knowledge_limit()
    test_workflow_resource_validation_batches_knowledge_bases()
    test_workflow_context_batches_prior_node_executions()
    test_workflow_start_node_outputs_question_files_and_globals()
    test_workflow_knowledge_node_limits_and_joins_results()
    test_workflow_knowledge_node_maxkb_settings_and_truncation()
    test_workflow_reranker_form_and_document_nodes()
    test_workflow_llm_node_dialogue_history_and_params()
    test_workflow_llm_node_reasoning_and_mcp_tool_loop()
    test_workflow_llm_result_streams_markdown_deltas()
    test_workflow_engine_propagates_worker_cancellation()
    test_upload_cleanup_tasks_are_registered()
    test_interaction_config_migration_upgrades_prerequisites()
    test_workflow_api_definition_publish_run_and_audit()
    test_workflow_agent_node_runs_one_durable_pinned_child()
    test_cancelling_queued_workflow_run_is_idempotent()
    test_workflow_executor_recovery_paths()
    print("WORKFLOW_SUITE_OK")


if __name__ == "__main__":
    main()
