"""Workflow engine and API regression suite.

Run from ``backend/`` with ``uv run python -m tests.workflows``.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import json

import tests.support  # noqa: F401

from app.shareddomain.workflows.engine import (
    NodeExecutionContext,
    NodeResult,
    NodeState,
    WorkflowEngine,
    WorkflowEngineError,
    WorkflowValidationError,
    validate_graph,
)
from app.shareddomain.workflows.defaults import default_workflow_graph
from tests.support import activate_admin, activate_user, auth_headers, test_client


def test_default_workflow_only_contains_start() -> None:
    graph = default_workflow_graph()

    assert [node.data.type for node in graph.nodes] == ["start"]
    assert graph.edges == []


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
                            "left": "{{start.question}}",
                            "operator": "equals",
                            "right": "yes",
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
                    "sourceHandle": "true",
                    "target": "yes",
                },
                {
                    "id": "e3",
                    "source": "condition",
                    "sourceHandle": "false",
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


def test_workflow_engine_runs_branch_and_join_deterministically() -> None:
    async def run() -> None:
        transitions = []

        async def execute(node, context):
            if node.data.type == "start":
                return NodeResult(outputs=context.workflow_inputs)
            if node.data.type == "condition":
                return NodeResult(selected_handles=frozenset({"true"}))
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
    from app.application.workflow_nodes import (
        _condition,
        _model_output_limit,
        resolve_value,
    )
    from app.schemas.workflow import KnowledgeNodeConfig

    assert _model_output_limit("openai_compatible", 12) == {"max_tokens": 12}
    assert _model_output_limit("google_genai", 12) == {"max_output_tokens": 12}
    assert _model_output_limit("ollama", 12) == {"num_predict": 12}
    assert _condition([1, 2, 3], "length_greater_than", 2)
    assert _condition(True, "is_true", None)
    assert not _condition(False, "is_true", None)
    assert _condition(2, "greater_than", 1.5)
    assert _condition(2.0, "greater_than", 1)
    for operator, left, right in (
        ("contains", "text", 1),
        ("not_contains", {"key": "value"}, ["key"]),
    ):
        try:
            _condition(left, operator, right)
        except ValueError as exc:
            assert "incompatible operands" in str(exc)
        else:
            raise AssertionError(f"{operator} accepted incompatible operands")
    try:
        _condition(3, "length_greater_than", 2)
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
            assert arguments == {"query": "question", "limit": 2}
            return SimpleNamespace(
                is_error=False,
                summary="ok",
                content="",
                output={
                    "hits": [
                        {"content": "first"},
                        {"content": "second"},
                        {"content": "third"},
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
            {"content": "first"},
            {"content": "second"},
        ]
        assert result.outputs["content"] == "first\n\nsecond"

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


def main() -> None:
    test_default_workflow_only_contains_start()
    test_workflow_validation_rejects_cycles_and_downstream_references()
    test_workflow_engine_runs_branch_and_join_deterministically()
    test_workflow_engine_enforces_step_and_token_budgets()
    test_workflow_model_output_limit_uses_provider_native_argument()
    test_workflow_start_node_outputs_question_files_and_globals()
    test_workflow_knowledge_node_limits_and_joins_results()
    test_workflow_engine_propagates_worker_cancellation()
    test_upload_cleanup_tasks_are_registered()
    test_interaction_config_migration_upgrades_prerequisites()
    test_workflow_api_definition_publish_run_and_audit()
    print("WORKFLOW_SUITE_OK")


if __name__ == "__main__":
    main()
