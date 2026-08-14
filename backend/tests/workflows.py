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
                        {"content": "first", "distance": 0.3},
                        {"content": "second", "distance": 0.7},
                        {"content": "third", "distance": 0.2},
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
        assert result.outputs["hits"] == [
            {"content": "first", "distance": 0.3},
            {"content": "second", "distance": 0.7},
        ]
        assert result.outputs["content"] == "first\n\nsecond"
        assert result.outputs["data"] == "first\n\nsecond"
        assert result.outputs["paragraph_list"][0]["distance"] == 0.3
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
        run.status = "running"
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
        assert await agent_repository.fail_exhausted_agent_runs(db, now) == 1
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
        assert draft_run.json()["status"] == "succeeded"
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
                    for index in range(10)
                ],
            ],
        )
        assert unlimited_upload.status_code == 201, unlimited_upload.text
        unlimited_upload_ids = [item["id"] for item in unlimited_upload.json()]
        assert len(unlimited_upload_ids) == 11

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
        assert len(public_payload["inputs"]["files"]) == 12
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


class _FakeLlmTool:
    name = "mcp_weather"
    metadata = {}
    arguments: dict | None = None

    async def ainvoke(self, arguments):
        self.arguments = arguments
        return AgentToolResult(content="sunny", summary="ok", output={"weather": "sunny"})


class _FakeLlmLedger:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def before(self, turn, call, metadata, arguments):
        self.calls.append(("before", turn, call["id"], dict(arguments)))
        return None

    async def after(self, turn, call, metadata, arguments, result):
        self.calls.append(("after", turn, call["id"], result.content))


def _llm_scope(**overrides) -> SimpleNamespace:
    scope = SimpleNamespace(
        run=SimpleNamespace(model_id="model-1"),
        settings=None,
        models={"model-1": SimpleNamespace(provider_type="openai_compatible")},
        mcp_tools={},
        node_order={"llm-1": 0},
        node_histories={},
        ledger=_FakeLlmLedger(),
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
        tool = _FakeLlmTool()
        ledger = _FakeLlmLedger()
        scope = _llm_scope(
            mcp_tools={("srv-1", "tool-1"): ("resolved", "policy")},
            ledger=ledger,
        )
        node = _llm_node(
            {
                "prompt": "hello",
                "mcp_enable": True,
                "mcp_servers": [{"server_id": "srv-1", "tool_name": "tool-1"}],
                "model_setting": {"reasoning_content_enable": True},
            }
        )
        with (
            patch(
                "app.application.workflow_nodes.build_chat_model",
                return_value=fake,
            ),
            patch(
                "app.application.workflow_nodes.build_mcp_agent_tool",
                return_value=tool,
            ),
        ):
            result = await execute_workflow_node(scope, node, _llm_context())
        assert result.outputs["text"] == "final answer"
        assert result.outputs["reasoning_content"] == "thinking..."
        assert result.model_tokens == 35
        assert ledger.calls == [
            ("before", 1, "workflow-llm-1-tool-0", {"city": "sh"}),
            ("after", 1, "workflow-llm-1-tool-0", "sunny"),
        ]
        assert tool.arguments == {"city": "sh"}
        assert fake.bound_tools == [tool]
        # the second model call carries the tool result
        second_messages = fake.calls[1][0]
        tool_messages = [
            item for item in second_messages if isinstance(item, ToolMessage)
        ]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "call-1"
        assert tool_messages[0].content == "sunny"

        # mcp_enable with an unbound tool fails the node
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
                            "mcp_enable": True,
                            "mcp_servers": [
                                {"server_id": "srv-1", "tool_name": "tool-1"}
                            ],
                        }
                    ),
                    _llm_context(),
                )
            except ValueError as exc:
                assert "unavailable or not read-only" in str(exc)
            else:
                raise AssertionError("unbound MCP tool was accepted")

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
    print("WORKFLOW_SUITE_OK")


if __name__ == "__main__":
    main()
