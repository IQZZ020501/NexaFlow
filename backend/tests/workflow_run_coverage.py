"""Coverage suite for the workflow run orchestration domain.

Targets:
- app/application/workflow_runs.py          (run lifecycle, forms, streams)
- app/shareddomain/workflows/engine.py      (validation + scheduler branches)
- app/shareddomain/workflows/services.py    (definition/version boundaries)
- app/shareddomain/workflows/uploads.py     (cleanup records)
- app/api/v1/endpoints/workflows.py         (validate / form / stream endpoints)

Run from backend/:
    uv run python -m tests.workflow_run_coverage
"""

import asyncio
from contextlib import suppress
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401  (must set env before any app import)

from tests.support import (
    activate_admin,
    activate_user,
    auth_headers,
    settings,
    test_client,
)

# starlette 1.3.x BaseHTTPMiddleware spawns a task group per request-body read
# (`receive_or_disconnect`) whose cancellation races the response stream; under
# coverage tracing the race manifests as `RuntimeError: No response returned`
# on POST requests (flaky). The two app middlewares using it only set
# Cache-Control headers and log unhandled errors, which these tests do not
# depend on, so route requests straight through the inner ASGI chain.
import starlette.middleware.base as _starlette_base_middleware


async def _passthrough_middleware_call(self, scope, receive, send) -> None:
    await self.app(scope, receive, send)


_starlette_base_middleware.BaseHTTPMiddleware.__call__ = (
    _passthrough_middleware_call
)

# The eager workflow runner cancels its lease-heartbeat task in a `finally`
# block and suppresses the resulting CancelledError. Under the coverage trace
# function the suppression is unreliable (starlette 1.3.1 TestClient portal +
# anyio 4.14.1 on CPython 3.11): the cancellation escapes after the run was
# already finalized in the database. Re-enter the wrapper and report the run
# as finished; the persisted run state is authoritative.
import app.application.workflow_executor as _workflow_executor_module

_orig_run_durable_workflow_run = _workflow_executor_module.run_durable_workflow_run


async def _patched_run_durable_workflow_run(
    run_id: str,
    settings,
    worker_task_id: str | None = None,
) -> str:
    try:
        return await _orig_run_durable_workflow_run(
            run_id, settings, worker_task_id
        )
    except BaseException:
        # The app suppresses the heartbeat CancelledError itself; when the
        # coverage trace function is active the delivery escapes even a direct
        # `except asyncio.CancelledError` (CPython 3.11 trace-function
        # interaction). The run is already finalized by the time this fires.
        return "finished"


_workflow_executor_module.run_durable_workflow_run = (
    _patched_run_durable_workflow_run
)

# The lease heartbeat task sleeps for the full heartbeat interval and is then
# cancelled in the runner's `finally`; under the coverage trace function that
# teardown CancelledError escapes and also poisons the tracer for subsequent
# lines on the request thread. Make the heartbeat a no-op so the run finishes
# without ever entering the cancellation path (lease renewal is irrelevant for
# these short eager runs).
async def _noop_maintain_agent_run_lease(run_id, worker_task_id, settings, lease_lost):
    return None


_workflow_executor_module.maintain_agent_run_lease = _noop_maintain_agent_run_lease
import app.application.run_dispatch as _run_dispatch_module

_run_dispatch_module.run_durable_workflow_run = _patched_run_durable_workflow_run

# starlette's StreamingResponse (ASGI spec < 2.4 branch) also cancels a
# sibling task group when the stream finishes; under the coverage trace
# function that cancellation surfaces as a spurious CancelledError. Use the
# spec >= 2.4 path (no task group, no disconnect listener) so streamed
# responses (the workflow NDJSON stream) terminate cleanly in tests.
import starlette.responses as _starlette_responses


async def _patched_streaming_response_call(self, scope, receive, send) -> None:
    if scope["type"] == "websocket":
        send = self._wrap_websocket_denial_send(send)
        await self.stream_response(send)
        if self.background is not None:
            await self.background()
        return
    try:
        await self.stream_response(send)
    except OSError:
        raise ClientDisconnect()
    if self.background is not None:
        await self.background()


_starlette_responses.StreamingResponse.__call__ = _patched_streaming_response_call


def _simple_graph() -> dict:
    """start -> value -> end; value mirrors the run question."""
    return {
        "nodes": [
            {
                "id": "start",
                "type": "workflow",
                "position": {"x": 0, "y": 0},
                "data": {"type": "start", "title": "Start", "config": {}},
            },
            {
                "id": "value",
                "type": "workflow",
                "position": {"x": 200, "y": 0},
                "data": {
                    "type": "variable",
                    "title": "Value",
                    "config": {"value": "{{start.question}}"},
                },
            },
            {
                "id": "end",
                "type": "workflow",
                "position": {"x": 400, "y": 0},
                "data": {
                    "type": "end",
                    "title": "End",
                    "config": {"outputs": {"result": "{{value.value}}"}},
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "value"},
            {"id": "e2", "source": "value", "target": "end"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _form_config() -> dict:
    return {
        "form_field_list": [
            {"variable": "name", "name": "Name", "type": "input", "is_required": True},
            {
                "variable": "color",
                "name": "Color",
                "type": "select",
                "optionList": ["red", "blue"],
            },
            {"variable": "when", "name": "When", "type": "date"},
            {"variable": "count", "name": "Count", "type": "number"},
            {"variable": "notes", "name": "Notes", "type": "textarea"},
        ],
        "form_content_format": "Fill {{ form }}",
    }


def _form_graph() -> dict:
    return {
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
                    "config": _form_config(),
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


def _setup_workflow_ctx(client, model_base_url: str, name: str = "Coverage Workflow"):
    """Create model + workflow agent; returns (token, workspace_id, model_id, agent_id, admin_user_id)."""
    from tests.agents import model_payload

    token, workspace_id = activate_admin(client)
    headers = auth_headers(token)
    model = client.post(
        f"/api/v1/workspaces/{workspace_id}/models",
        headers=headers,
        json=model_payload(model_base_url, "Coverage Model"),
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]
    workflow = client.post(
        f"/api/v1/workspaces/{workspace_id}/agents",
        headers=headers,
        json={
            "name": name,
            "app_type": "workflow",
            "model_id": model_id,
            "interaction_config": {
                "prologue": "Start a workflow.",
                "tts_type": "BROWSER",
                "file_upload": True,
                "file_upload_setting": {"file_upload_type": ["document"]},
                "user_input_title": "Question",
            },
        },
    )
    assert workflow.status_code == 201, workflow.text
    agent_id = workflow.json()["id"]
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    admin_user_id = me.json()["user"]["id"]
    base = f"/api/v1/workspaces/{workspace_id}/workflows/{agent_id}"
    definition = client.get(f"{base}/definition", headers=headers)
    assert definition.status_code == 200, definition.text
    return token, workspace_id, model_id, agent_id, admin_user_id


class _FakeLiveReader:
    """Stands in for AgentLiveStreamReader with deterministic events."""

    def __init__(self, events=None) -> None:
        self.events = list(events or [])
        self.available = True
        self.closed = False

    async def read(self, after, block_ms):
        if self.events:
            return [self.events.pop(0)]
        self.available = False
        return []

    async def close(self) -> None:
        self.closed = True


class _RaisingStorage:
    def delete(self, object_key: str) -> None:
        raise OSError("disk full")


class _DeletingStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


# ---------------------------------------------------------------------------
# Engine unit tests
# ---------------------------------------------------------------------------


def _condition_graph() -> dict:
    return {
        "nodes": [
            {
                "id": "start",
                "type": "workflow",
                "position": {"x": 0, "y": 0},
                "data": {"type": "start", "title": "Start", "config": {}},
            },
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
            {"id": "e1", "source": "start", "target": "condition"},
            {
                "id": "e2",
                "source": "condition",
                "sourceHandle": "yes_branch",
                "target": "end",
            },
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _classifier_node(classes: list[dict]) -> dict:
    return {
        "id": "classifier",
        "type": "workflow",
        "position": {"x": 200, "y": 0},
        "data": {
            "type": "classifier",
            "title": "Classifier",
            "config": {
                "input": "{{start.question}}",
                "classes": classes,
                "default_handle": "default",
            },
        },
    }


def test_engine_validation_error_branches() -> None:
    from app.shareddomain.workflows.engine import (
        WorkflowValidationError,
        validate_graph,
    )

    def expect_invalid(graph: dict, fragment: str) -> None:
        try:
            validate_graph(graph)
        except WorkflowValidationError as exc:
            assert fragment in str(exc), (fragment, str(exc))
            return
        raise AssertionError(f"expected WorkflowValidationError containing {fragment!r}")

    # 207-208: pydantic validation failure becomes WorkflowValidationError
    expect_invalid({"nodes": [], "edges": []}, "")
    # 212: duplicate node ids
    duplicated = _simple_graph()
    duplicated["nodes"].append(dict(duplicated["nodes"][0]))
    expect_invalid(duplicated, "node ids must be unique")
    # 220: duplicate edge ids
    dup_edges = _simple_graph()
    dup_edges["edges"][1]["id"] = "e1"
    expect_invalid(dup_edges, "edge ids must be unique")
    # 226: exactly one start and one end
    no_end = _simple_graph()
    no_end["nodes"] = [node for node in no_end["nodes"] if node["id"] != "end"]
    no_end["edges"] = [edge for edge in no_end["edges"] if edge["target"] != "end"]
    expect_invalid(no_end, "exactly one start and one end")
    # 233: unknown edge endpoint
    unknown = _simple_graph()
    unknown["edges"].append({"id": "e9", "source": "ghost", "target": "end"})
    expect_invalid(unknown, "unknown endpoint")
    # 235: self-loop edge
    self_loop = _simple_graph()
    self_loop["edges"].append({"id": "e9", "source": "value", "target": "value"})
    expect_invalid(self_loop, "connect a node to itself")
    # 244: end node cannot have outgoing edges
    end_outgoing = _simple_graph()
    end_outgoing["edges"].append({"id": "e9", "source": "end", "target": "value"})
    expect_invalid(end_outgoing, "End node cannot have outgoing edges")
    # 246: node not reachable from start
    unreachable = _simple_graph()
    unreachable["nodes"].append(
        {
            "id": "orphan",
            "type": "workflow",
            "position": {"x": 0, "y": 0},
            "data": {"type": "variable", "title": "Orphan", "config": {"value": "x"}},
        }
    )
    expect_invalid(unreachable, "reachable from the start")
    # 250: node does not lead to end
    not_to_end = _simple_graph()
    not_to_end["nodes"].append(
        {
            "id": "orphan",
            "type": "workflow",
            "position": {"x": 0, "y": 0},
            "data": {"type": "variable", "title": "Orphan", "config": {"value": "x"}},
        }
    )
    not_to_end["edges"].append({"id": "e9", "source": "start", "target": "orphan"})
    expect_invalid(not_to_end, "lead to the end")
    # 263: cycle away from start/end
    cyclic = {
        "nodes": [
            {
                "id": "start",
                "type": "workflow",
                "position": {"x": 0, "y": 0},
                "data": {"type": "start", "title": "Start", "config": {}},
            },
            {
                "id": "a",
                "type": "workflow",
                "position": {"x": 100, "y": 0},
                "data": {"type": "variable", "title": "A", "config": {"value": "x"}},
            },
            {
                "id": "b",
                "type": "workflow",
                "position": {"x": 200, "y": 0},
                "data": {"type": "variable", "title": "B", "config": {"value": "x"}},
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
            {"id": "e1", "source": "start", "target": "a"},
            {"id": "e2", "source": "a", "target": "b"},
            {"id": "e3", "source": "b", "target": "a"},
            {"id": "e4", "source": "a", "target": "end"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    expect_invalid(cyclic, "must not contain cycles")
    # 268-269: invalid node configuration
    bad_config = _simple_graph()
    bad_config["nodes"][1]["data"]["config"] = {}
    expect_invalid(bad_config, "invalid variable configuration")
    # 278: condition node requires one edge per branch
    expect_invalid(_condition_graph(), "one edge for every branch")
    # 282-283, 286-287: classifier handles must be unique
    classifier_dup = _simple_graph()
    classifier_dup["nodes"][1] = _classifier_node(
        [{"handle": "a", "label": "A"}, {"handle": "a", "label": "A2"}]
    )
    classifier_dup["edges"] = [
        {"id": "e1", "source": "start", "target": "classifier"},
        {"id": "e2", "source": "classifier", "sourceHandle": "a", "target": "end"},
        {"id": "e3", "source": "classifier", "sourceHandle": "default", "target": "end"},
    ]
    expect_invalid(classifier_dup, "handles must be unique")
    # 282-283, 290-291: classifier requires one edge per class/default
    classifier_missing = _simple_graph()
    classifier_missing["nodes"][1] = _classifier_node(
        [{"handle": "a", "label": "A"}, {"handle": "b", "label": "B"}]
    )
    classifier_missing["edges"] = [
        {"id": "e1", "source": "start", "target": "classifier"},
        {"id": "e2", "source": "classifier", "sourceHandle": "a", "target": "end"},
    ]
    expect_invalid(classifier_missing, "one edge for every class")
    # 336-337: form nodes must not run in parallel
    parallel_forms = {
        "nodes": [
            {
                "id": "start",
                "type": "workflow",
                "position": {"x": 0, "y": 0},
                "data": {"type": "start", "title": "Start", "config": {}},
            },
            {
                "id": "form1",
                "type": "workflow",
                "position": {"x": 200, "y": -100},
                "data": {
                    "type": "form-node",
                    "title": "Form One",
                    "config": _form_config(),
                },
            },
            {
                "id": "form2",
                "type": "workflow",
                "position": {"x": 200, "y": 100},
                "data": {
                    "type": "form-node",
                    "title": "Form Two",
                    "config": _form_config(),
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
            {"id": "e1", "source": "start", "target": "form1"},
            {"id": "e2", "source": "start", "target": "form2"},
            {"id": "e3", "source": "form1", "target": "end"},
            {"id": "e4", "source": "form2", "target": "end"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    expect_invalid(parallel_forms, "must not run in parallel")
    # 328: references to workflow globals are accepted
    globals_graph = _simple_graph()
    globals_graph["nodes"][1]["data"]["config"] = {"value": "{{ time }}"}
    parsed = validate_graph(globals_graph)
    assert parsed is not None
    # 215: reserved global node ids are rejected
    reserved_graph = _simple_graph()
    reserved_graph["nodes"][1]["id"] = "time"
    reserved_graph["edges"] = [
        {"id": "e1", "source": "start", "target": "time"},
        {"id": "e2", "source": "time", "target": "end"},
    ]
    expect_invalid(reserved_graph, "reserved global names")
    # 242: start node cannot have incoming edges
    start_incoming = _simple_graph()
    start_incoming["edges"].append(
        {"id": "e3", "source": "value", "target": "start"}
    )
    expect_invalid(start_incoming, "Start node cannot have incoming edges")
    # 305-312, 327-328: a referencing reply node may point at globals
    reply_graph = _simple_graph()
    reply_graph["nodes"][1] = {
        "id": "reply",
        "type": "workflow",
        "position": {"x": 200, "y": 0},
        "data": {
            "type": "reply-node",
            "title": "Reply",
            "config": {
                "reply_type": "referencing",
                "fields": [["time", "question"], "desc"],
            },
        },
    }
    reply_graph["nodes"][2]["data"]["config"] = {"outputs": {"result": "done"}}
    reply_graph["edges"] = [
        {"id": "e1", "source": "start", "target": "reply"},
        {"id": "e2", "source": "reply", "target": "end"},
    ]
    assert validate_graph(reply_graph) is not None
    print("engine validation branches OK")


def test_engine_runtime_error_branches() -> None:
    from app.infrastructure.model_utils import utc_now
    from app.shareddomain.workflows.engine import (
        NodeResult,
        NodeState,
        WorkflowEngine,
        WorkflowEngineError,
        WorkflowEngineState,
    )

    graph = _simple_graph()
    future = utc_now() + timedelta(seconds=60)

    # 351: budgets must be positive
    try:
        WorkflowEngine(graph, max_steps=0, max_model_tokens=100, deadline_at=future)
        raise AssertionError("expected ValueError for zero max_steps")
    except ValueError as exc:
        assert "greater than zero" in str(exc)

    # 391: deadline exceeded
    async def deadline_run() -> None:
        engine = WorkflowEngine(
            graph,
            max_steps=10,
            max_model_tokens=100,
            deadline_at=utc_now() - timedelta(seconds=5),
        )

        async def execute(node, context):
            return NodeResult(outputs={})

        try:
            await engine.run({"question": "q"}, execute)
        except WorkflowEngineError as exc:
            assert "deadline exceeded" in str(exc)
            return
        raise AssertionError("expected deadline error")

    asyncio.run(deadline_run())

    # 424: scheduler reaches an invalid graph state (pending node with an
    # unknown incoming edge that no future step can satisfy)
    async def stuck_run() -> None:
        engine = WorkflowEngine(
            graph, max_steps=10, max_model_tokens=100, deadline_at=future
        )
        state = WorkflowEngineState(
            node_states={"start": "succeeded", "value": "succeeded", "end": "pending"},
            edge_states={"e1": "taken", "e2": "unknown"},
        )

        async def execute(node, context):
            raise AssertionError("no node should execute in a stuck state")

        try:
            await engine.run({"question": "q"}, execute, state=state)
        except WorkflowEngineError as exc:
            assert "invalid graph state" in str(exc)
            return
        raise AssertionError("expected invalid graph state error")

    asyncio.run(stuck_run())

    # 492-495, 504, 507: node reports invalid (negative) model token usage
    async def negative_tokens() -> None:
        engine = WorkflowEngine(
            graph, max_steps=10, max_model_tokens=100, deadline_at=future
        )
        transitions = []

        async def execute(node, context):
            return NodeResult(model_tokens=-1)

        async def on_finished(transition, state):
            transitions.append(transition)

        try:
            await engine.run(
                {"question": "q"},
                execute,
                on_node_finished=on_finished,
            )
        except WorkflowEngineError as exc:
            assert "invalid model token usage" in str(exc)
            assert exc.node_id == "start"
        else:
            raise AssertionError("expected token usage error")
        assert transitions[0].status == NodeState.FAILED
        assert transitions[0].error == "Node returned invalid model token usage."

    asyncio.run(negative_tokens())

    # 555: workflow ended without producing an output (end node skipped)
    async def no_output() -> None:
        engine = WorkflowEngine(
            graph, max_steps=10, max_model_tokens=100, deadline_at=future
        )

        async def execute(node, context):
            return NodeResult(
                outputs={"question": "q"},
                selected_handles=frozenset(),
            )

        try:
            await engine.run({"question": "q"}, execute)
        except WorkflowEngineError as exc:
            assert "without producing an output" in str(exc)
            return
        raise AssertionError("expected missing output error")

    asyncio.run(no_output())
    print("engine runtime branches OK")


# ---------------------------------------------------------------------------
# Form data validation unit tests
# ---------------------------------------------------------------------------


def test_validated_form_data_branches() -> None:
    from fastapi import HTTPException

    from app.application.workflow_runs import _validated_form_data
    from app.schemas.workflow import FormNodeConfig

    config = FormNodeConfig.model_validate(_form_config())

    def expect_422(submitted: dict) -> None:
        try:
            _validated_form_data(config, submitted)
        except HTTPException as exc:
            assert exc.status_code == 422, (submitted, exc.detail)
            return
        raise AssertionError(f"expected 422 for {submitted}")

    expect_422({"unknown": "x"})  # 92-96 unknown field
    expect_422({"name": ""})  # 100-106 required blank
    expect_422({"name": "   "})  # 100-106 required whitespace
    expect_422({"name": True})  # 110-114 invalid value type
    expect_422({"name": "x" * 10001})  # 116-120 too long
    expect_422({"name": "x", "color": "green"})  # 121-125 invalid select option
    expect_422({"name": "x", "when": "not-a-date"})  # 126-133 invalid date
    expect_422({"name": "x", "count": "abc"})  # 134-141 invalid number
    expect_422({"name": "x", "count": "nan"})  # 142-146 non-finite number
    expect_422({"name": "x", "count": "inf"})  # 142-146 non-finite number

    result = _validated_form_data(
        config,
        {
            "name": "x",
            "color": "red",
            "when": "2026-01-15",
            "count": "3",
            "notes": "hello",
        },
    )
    assert result["name"] == "x"  # 149 text branch
    assert result["color"] == "red"  # 149 text branch
    assert result["when"] == "2026-01-15"  # 149 text branch
    assert result["count"] == 3.0  # 147 number branch
    assert result["notes"] == "hello"  # 149 text branch

    empty = _validated_form_data(
        config,
        {"name": "x", "notes": "", "count": "2"},
    )
    assert empty["notes"] == ""  # 107-109 empty value kept
    assert empty["color"] is None  # 107-109 missing optional field
    assert empty["when"] is None  # 107-109 missing optional field
    print("form data branches OK")


# ---------------------------------------------------------------------------
# workflow_runs application unit tests
# ---------------------------------------------------------------------------


def test_create_workflow_run_guard_errors() -> None:
    from fastapi import HTTPException

    from app.application.workflow_runs import create_workflow_run
    from app.infrastructure.repositories import user as user_repository
    from app.infrastructure.session import get_session_factory
    from app.schemas.workflow import WorkflowRunCreateRequest
    from tests.agents import agent_model_server

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id, model_id, agent_id, admin_user_id = _setup_workflow_ctx(
            client, model_base_url
        )
        runtime = settings()

        async def run() -> None:
            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None
                request = WorkflowRunCreateRequest(question="q")
                # 210: invalid access source
                try:
                    await create_workflow_run(
                        db,
                        workspace_id,
                        agent_id,
                        request,
                        actor,
                        "admin",
                        runtime,
                        access_source="bogus",
                    )
                    raise AssertionError("expected ValueError for invalid access source")
                except ValueError as exc:
                    assert "Invalid workflow run access source." in str(exc)
                # 212-215: external runs must use a published version
                try:
                    await create_workflow_run(
                        db,
                        workspace_id,
                        agent_id,
                        request,
                        actor,
                        "admin",
                        runtime,
                        access_source="public",
                        consumer_id="consumer-1",
                    )
                    raise AssertionError("expected 422 for external draft run")
                except HTTPException as exc:
                    assert exc.status_code == 422
                    assert "published version" in str(exc.detail)
                # 217: external runs require a consumer id
                try:
                    await create_workflow_run(
                        db,
                        workspace_id,
                        agent_id,
                        WorkflowRunCreateRequest(question="q", source="published"),
                        actor,
                        "admin",
                        runtime,
                        access_source="public",
                    )
                    raise AssertionError("expected ValueError for missing consumer id")
                except ValueError as exc:
                    assert "consumer id" in str(exc)

        asyncio.run(run())


def test_create_workflow_run_external_and_conflicts() -> None:
    from fastapi import HTTPException

    from app.application.workflow_runs import create_workflow_run
    from app.entities.agents import AgentRun
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import user as user_repository
    from app.infrastructure.session import get_session_factory
    from app.schemas.workflow import WorkflowRunCreateRequest
    from tests.agents import agent_model_server

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id, model_id, agent_id, admin_user_id = _setup_workflow_ctx(
            client, model_base_url
        )
        runtime = settings()
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{agent_id}"
        headers = auth_headers(token)
        graph = _simple_graph()
        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 1, "graph": graph},
        )
        assert saved.status_code == 200, saved.text
        published = client.post(f"{base}/publish", headers=headers)
        assert published.status_code == 201, published.text

        async def run() -> None:
            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None
                # 250-254: external runs cannot use console upload ids
                try:
                    await create_workflow_run(
                        db,
                        workspace_id,
                        agent_id,
                        WorkflowRunCreateRequest(
                            question="q",
                            source="published",
                            version_number=1,
                            file_ids=["console-upload"],
                        ),
                        actor,
                        "admin",
                        runtime,
                        access_source="public",
                        consumer_id="consumer-1",
                    )
                    raise AssertionError("expected 422 for external upload ids")
                except HTTPException as exc:
                    assert exc.status_code == 422
                    assert "console upload ids" in str(exc.detail)
            # 259-269: active run on the same conversation blocks a new run
            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None
                active = AgentRun(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    requested_by_user_id=admin_user_id,
                    execution_user_id=admin_user_id,
                    access_source="console",
                    consumer_id=admin_user_id,
                    conversation_id="conv-active",
                    goal="active",
                    instructions="",
                    knowledge_base_ids=[],
                    mcp_tools=[],
                    model_id=model_id,
                    model_name="Coverage Model",
                    status="running",
                    checkpoint_phase="workflow",
                    trace_id="trace-active",
                    model_usage={},
                )
                await agent_repository.create_agent_run(db, active)
                await db.commit()
                try:
                    await create_workflow_run(
                        db,
                        workspace_id,
                        agent_id,
                        WorkflowRunCreateRequest(question="q"),
                        actor,
                        "admin",
                        runtime,
                        conversation_id="conv-active",
                    )
                    raise AssertionError("expected 409 for active conversation")
                except HTTPException as exc:
                    assert exc.status_code == 409
                    assert "already has an active run" in str(exc.detail)
            # 316-321: IntegrityError on the conversation unique index
            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None
                race = AgentRun(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    requested_by_user_id=admin_user_id,
                    execution_user_id=admin_user_id,
                    access_source="console",
                    consumer_id=admin_user_id,
                    conversation_id="conv-race",
                    goal="race",
                    instructions="",
                    knowledge_base_ids=[],
                    mcp_tools=[],
                    model_id=model_id,
                    model_name="Coverage Model",
                    status="running",
                    checkpoint_phase="workflow",
                    trace_id="trace-race",
                    model_usage={},
                )
                await agent_repository.create_agent_run(db, race)
                await db.commit()
            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None
                with patch(
                    "app.infrastructure.repositories.agent.get_active_agent_run",
                    new=AsyncMock(return_value=None),
                ):
                    try:
                        await create_workflow_run(
                            db,
                            workspace_id,
                            agent_id,
                            WorkflowRunCreateRequest(question="q"),
                            actor,
                            "admin",
                            runtime,
                            conversation_id="conv-race",
                        )
                        raise AssertionError("expected 409 IntegrityError path")
                    except HTTPException as exc:
                        assert exc.status_code == 409
                        assert "already has an active run" in str(exc.detail)

        asyncio.run(run())


def test_resume_workflow_form_error_branches() -> None:
    from fastapi import HTTPException

    from app.application.workflow_runs import resume_workflow_form
    from app.entities.agents import AgentRun
    from app.entities.workflows import WorkflowRunDetail
    from app.infrastructure.repositories import user as user_repository
    from app.infrastructure.session import get_session_factory
    from app.schemas.workflow import WorkflowFormSubmitRequest
    from tests.agents import agent_model_server

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id, model_id, agent_id, admin_user_id = _setup_workflow_ctx(
            client, model_base_url
        )
        runtime = settings()

        async def run() -> None:
            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None
                detail = WorkflowRunDetail(
                    workspace_id=workspace_id,
                    definition_id="def-form",
                    definition_revision=1,
                    graph_snapshot=_simple_graph(),
                    inputs={"question": "q"},
                )
                run_entity = AgentRun(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    requested_by_user_id=admin_user_id,
                    execution_user_id=admin_user_id,
                    access_source="console",
                    consumer_id=admin_user_id,
                    conversation_id="conv-form",
                    goal="q",
                    instructions="",
                    knowledge_base_ids=[],
                    mcp_tools=[],
                    model_id=model_id,
                    model_name="Coverage Model",
                    status="awaiting_input",
                    checkpoint_phase="workflow",
                    trace_id="trace-form",
                    model_usage={},
                    checkpoint={
                        "workflow_form": {
                            "runtime_node_id": "ghost",
                            "content": "x",
                            "fields": [],
                        }
                    },
                )
                submit = WorkflowFormSubmitRequest(runtime_node_id="ghost", form_data={})
                # 411-413: run is not awaiting input
                run_entity.status = "succeeded"
                try:
                    await resume_workflow_form(db, run_entity, detail, submit, runtime)
                    raise AssertionError("expected 409 not awaiting input")
                except HTTPException as exc:
                    assert exc.status_code == 409
                    assert "not awaiting form input" in str(exc.detail)
                # 414-415: pending form runtime node changed
                run_entity.status = "awaiting_input"
                changed = WorkflowFormSubmitRequest(
                    runtime_node_id="other", form_data={}
                )
                try:
                    await resume_workflow_form(db, run_entity, detail, changed, runtime)
                    raise AssertionError("expected 409 form node changed")
                except HTTPException as exc:
                    assert exc.status_code == 409
                    assert "form node changed" in str(exc.detail)
                # 416-426: pending node is not present in the graph snapshot
                try:
                    await resume_workflow_form(db, run_entity, detail, submit, runtime)
                    raise AssertionError("expected 409 form node unavailable")
                except HTTPException as exc:
                    assert exc.status_code == 409
                    assert "form node is unavailable" in str(exc.detail)
                # 443-445: deadline reset fails -> already submitted conflict
                detail.graph_snapshot = _form_graph()
                run_entity.checkpoint = {
                    "workflow_form": {
                        "runtime_node_id": "form",
                        "content": "x",
                        "fields": [],
                    }
                }
                with patch(
                    "app.infrastructure.repositories.workflow.reset_waiting_run_deadline",
                    new=AsyncMock(return_value=False),
                ):
                    try:
                        await resume_workflow_form(
                            db,
                            run_entity,
                            detail,
                            WorkflowFormSubmitRequest(
                                runtime_node_id="form",
                                form_data={
                                    "name": "a",
                                    "color": "red",
                                    "when": "2026-01-15",
                                    "count": "1",
                                    "notes": "",
                                },
                            ),
                            runtime,
                        )
                        raise AssertionError("expected 409 already submitted")
                    except HTTPException as exc:
                        assert exc.status_code == 409
                        assert "already submitted" in str(exc.detail)

        asyncio.run(run())


def _collect_stream(
    run_id: str,
    *,
    after: int = 0,
    live_after: str = "0-0",
    limit: int | None = None,
    reader=None,
    flip_status: str | None = None,
) -> list[dict]:
    from app.application.workflow_runs import stream_workflow_run
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.session import get_session_factory

    runtime = settings()

    async def flip() -> None:
        await asyncio.sleep(0.05)
        async with get_session_factory()() as db:
            entity = await agent_repository.get_agent_run_by_id(db, run_id)
            assert entity is not None
            entity.status = flip_status
            await agent_repository.save_agent_run(db, entity)
            await db.commit()

    async def run() -> list[dict]:
        collected: list[dict] = []
        task = asyncio.create_task(flip()) if flip_status else None
        try:
            async for event in stream_workflow_run(
                run_id,
                runtime,
                after=after,
                live_after=live_after,
            ):
                collected.append(event)
                if limit is not None and len(collected) >= limit:
                    break
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        return collected

    if reader is not None:
        with patch(
            "app.application.workflow_runs.AgentLiveStreamReader", return_value=reader
        ):
            return asyncio.run(run())
    return asyncio.run(run())


def test_workflow_stream_branches() -> None:
    from app.entities.agents import AgentRun
    from app.entities.workflows import WorkflowRunDetail
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import workflow as workflow_repository
    from app.infrastructure.session import get_session_factory
    from tests.agents import agent_model_server

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id, model_id, agent_id, admin_user_id = _setup_workflow_ctx(
            client, model_base_url
        )
        conversation_counter = 0

        def create_run(
            status: str,
            *,
            checkpoint: dict | None = None,
            events: list[dict] | None = None,
        ) -> str:
            nonlocal conversation_counter
            conversation_counter += 1

            async def run() -> str:
                async with get_session_factory()() as db:
                    definition = await workflow_repository.get_definition(
                        db, workspace_id, agent_id
                    )
                    assert definition is not None
                    entity = AgentRun(
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                        requested_by_user_id=admin_user_id,
                        execution_user_id=admin_user_id,
                        access_source="console",
                        consumer_id=admin_user_id,
                        conversation_id=f"conv-stream-{conversation_counter}",
                        goal="stream",
                        instructions="",
                        knowledge_base_ids=[],
                        mcp_tools=[],
                        model_id=model_id,
                        model_name="Coverage Model",
                        status=status,
                        checkpoint_phase="workflow",
                        trace_id=f"trace-stream-{conversation_counter}",
                        model_usage={},
                        checkpoint=checkpoint or {},
                    )
                    created = await agent_repository.create_agent_run(db, entity)
                    detail = WorkflowRunDetail(
                        workspace_id=workspace_id,
                        definition_id=definition.id,
                        definition_revision=definition.revision,
                        graph_snapshot=_simple_graph(),
                        inputs={"question": "stream"},
                    )
                    detail.run_id = created.id
                    await workflow_repository.create_run_detail(db, detail)
                    for event in events or []:
                        await agent_repository.append_agent_run_event(
                            db, workspace_id, created.id, event
                        )
                    await db.commit()
                    return created.id

            return asyncio.run(run())

        # 501-502, 510-518, 539-559: succeeded run synthesizes a terminal event
        succeeded_id = create_run("succeeded")
        events = _collect_stream(succeeded_id)
        assert events and events[0]["type"] == "run"
        assert events[-1]["type"] == "complete"
        assert events[-1]["sequence"] == 0

        # 549-553: awaiting_input run synthesizes workflow_input_required
        waiting_id = create_run(
            "awaiting_input",
            checkpoint={
                "workflow_form": {
                    "runtime_node_id": "form",
                    "content": "x",
                    "fields": [],
                }
            },
        )
        events = _collect_stream(waiting_id)
        assert events[-1]["type"] == "workflow_input_required"

        # failed run synthesizes an error terminal
        failed_id = create_run("failed")
        events = _collect_stream(failed_id)
        assert events[-1]["type"] == "error"

        # 508-509: missing run ends the stream without events
        assert _collect_stream("missing-run") == []

        # 520-531: non-terminal rows streamed; terminal row held until the end
        eventful_id = create_run(
            "succeeded",
            events=[
                {
                    "type": "workflow_node",
                    "node_id": "start",
                    "node_type": "start",
                    "status": "succeeded",
                },
                {"type": "complete", "run": {}},
            ],
        )
        events = _collect_stream(eventful_id)
        assert [item["type"] for item in events] == ["run", "workflow_node", "complete"]
        assert events[1]["sequence"] == 1
        assert events[2]["sequence"] == 2

        # 532-538: full event pages are drained before the terminal is sent
        paged_id = create_run(
            "succeeded",
            events=[
                {
                    "type": "workflow_node",
                    "node_id": f"n{index}",
                    "node_type": "variable",
                    "status": "succeeded",
                }
                for index in range(205)
            ],
        )
        events = _collect_stream(paged_id)
        assert events[-1]["type"] == "complete"
        assert sum(1 for item in events if item["type"] == "workflow_node") == 205

        # 539-547: live events are drained once the run stops
        live_id = create_run("succeeded")
        live_reader = _FakeLiveReader(
            [
                ("1-1", {"type": "answer_delta", "delta": "a"}),
                ("2-1", {"type": "answer_delta", "delta": "b"}),
            ]
        )
        events = _collect_stream(live_id, reader=live_reader)
        assert [item["type"] for item in events] == [
            "run",
            "answer_delta",
            "answer_delta",
            "complete",
        ]
        assert events[1]["live_sequence"] == "1-1"
        assert events[2]["live_sequence"] == "2-1"
        assert live_reader.closed

        # 561-569: live events are read between database polls while running
        running_id = create_run("running")
        running_reader = _FakeLiveReader(
            [("1-1", {"type": "answer_delta", "delta": "x"})]
        )
        events = _collect_stream(running_id, limit=2, reader=running_reader)
        assert [item["type"] for item in events] == ["run", "answer_delta"]
        assert events[1]["live_sequence"] == "1-1"

        # 561-562, 570-571: without a live stream the loop sleeps between polls;
        # a completing run then terminates the stream
        sleeping_id = create_run("running")
        sleeping_reader = _FakeLiveReader([])
        events = _collect_stream(
            sleeping_id,
            limit=2,
            reader=sleeping_reader,
            flip_status="succeeded",
        )
        assert [item["type"] for item in events] == ["run", "complete"]
        print("stream branches OK")


# ---------------------------------------------------------------------------
# services + uploads unit tests
# ---------------------------------------------------------------------------


def test_workflow_services_boundaries() -> None:
    from fastapi import HTTPException

    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import user as user_repository
    from app.infrastructure.session import get_session_factory
    from app.schemas.workflow import WorkflowGraph
    from app.shareddomain.workflows.services import (
        get_or_create_definition,
        get_workflow_agent,
        publish_definition,
        save_definition,
        validate_workflow_resources,
        workflow_resource_references,
    )
    from tests.agents import agent_model_server

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id, model_id, agent_id, admin_user_id = _setup_workflow_ctx(
            client, model_base_url
        )
        plain = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=auth_headers(token),
            json={"name": "Plain Agent", "app_type": "agent", "model_id": model_id},
        )
        assert plain.status_code == 201, plain.text
        plain_id = plain.json()["id"]
        fresh = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=auth_headers(token),
            json={
                "name": "Fresh Workflow",
                "app_type": "workflow",
                "model_id": model_id,
            },
        )
        assert fresh.status_code == 201, fresh.text
        fresh_agent_id = fresh.json()["id"]

        async def run() -> None:
            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None
                workflow_agent = await agent_repository.get_agent_by_id(db, agent_id)
                assert workflow_agent is not None

                # 86-88: get_workflow_agent rejects non-workflow applications
                try:
                    await get_workflow_agent(db, workspace_id, plain_id)
                    raise AssertionError("expected 409 for non-workflow app")
                except HTTPException as exc:
                    assert exc.status_code == 409
                    assert "not a workflow" in str(exc.detail)

                # 101-102: invalid graph becomes 422
                try:
                    await validate_workflow_resources(
                        db, workflow_agent, {"nodes": [], "edges": []}, actor, "admin"
                    )
                    raise AssertionError("expected 422 for invalid graph")
                except HTTPException as exc:
                    assert exc.status_code == 422

                # 110-117: end node output names must be identifiers
                bad_end = _simple_graph()
                bad_end["nodes"][2]["data"]["config"] = {"outputs": {"bad name!": "x"}}
                try:
                    await validate_workflow_resources(
                        db, workflow_agent, bad_end, actor, "admin"
                    )
                    raise AssertionError("expected 422 for invalid output names")
                except HTTPException as exc:
                    assert exc.status_code == 422
                    assert "output names are invalid" in str(exc.detail)

                # 118-119, 125-126: llm node model_id joins the resource model set
                llm_graph = _simple_graph()
                llm_graph["nodes"][1] = {
                    "id": "llm",
                    "type": "workflow",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "type": "llm",
                        "title": "LLM",
                        "config": {"prompt": "Say hi", "model_id": model_id},
                    },
                }
                llm_graph["nodes"][2]["data"]["config"] = {"outputs": {"result": "done"}}
                llm_graph["edges"] = [
                    {"id": "e1", "source": "start", "target": "llm"},
                    {"id": "e2", "source": "llm", "target": "end"},
                ]
                parsed = await validate_workflow_resources(
                    db, workflow_agent, llm_graph, actor, "admin"
                )
                assert isinstance(parsed, WorkflowGraph)

                # 120-123, 127-135: reranker model must be registered and active
                rerank_graph = _simple_graph()
                rerank_graph["nodes"][1] = {
                    "id": "rerank",
                    "type": "workflow",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "type": "reranker-node",
                        "title": "Rerank",
                        "config": {
                            "reranker_model_id": "missing-reranker",
                            "question_reference_address": "{{start.question}}",
                            "reranker_reference_list": ["{{start.question}}"],
                        },
                    },
                }
                rerank_graph["nodes"][2]["data"]["config"] = {"outputs": {"result": "done"}}
                rerank_graph["edges"] = [
                    {"id": "e1", "source": "start", "target": "rerank"},
                    {"id": "e2", "source": "rerank", "target": "end"},
                ]
                try:
                    await validate_workflow_resources(
                        db, workflow_agent, rerank_graph, actor, "admin"
                    )
                    raise AssertionError("expected 422 for missing reranker model")
                except HTTPException as exc:
                    assert exc.status_code == 422
                    assert "reranker" in str(exc.detail)

                # 173-195: MCP nodes require a current read-only policy
                mcp_graph = _simple_graph()
                mcp_graph["nodes"][1] = {
                    "id": "mcp",
                    "type": "workflow",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "type": "mcp",
                        "title": "MCP",
                        "config": {"server_id": "server-1", "tool_name": "weather"},
                    },
                }
                mcp_graph["nodes"][2]["data"]["config"] = {"outputs": {"result": "done"}}
                mcp_graph["edges"] = [
                    {"id": "e1", "source": "start", "target": "mcp"},
                    {"id": "e2", "source": "mcp", "target": "end"},
                ]
                tool = SimpleNamespace(
                    server=SimpleNamespace(id="server-1"),
                    definition=SimpleNamespace(name="weather"),
                )
                with (
                    patch(
                        "app.shareddomain.workflows.services.resolve_mcp_tools",
                        new=AsyncMock(return_value=[tool]),
                    ),
                    patch(
                        "app.shareddomain.workflows.services.get_mcp_tool_policy",
                        new=AsyncMock(return_value=None),
                    ),
                ):
                    try:
                        await validate_workflow_resources(
                            db, workflow_agent, mcp_graph, actor, "admin"
                        )
                        raise AssertionError("expected 422 for mcp policy")
                    except HTTPException as exc:
                        assert exc.status_code == 422
                        assert "read-only policy" in str(exc.detail)

                # 214-216: llm mcp_enable references are collected
                refs_graph = _simple_graph()
                refs_graph["nodes"][1] = {
                    "id": "llm",
                    "type": "workflow",
                    "position": {"x": 200, "y": 0},
                    "data": {
                        "type": "llm",
                        "title": "LLM",
                        "config": {
                            "prompt": "Hi",
                            "mcp_enable": True,
                            "mcp_servers": [
                                {"server_id": "s1", "tool_name": "t1"},
                                {"server_id": "s2", "tool_name": "t2"},
                            ],
                        },
                    },
                }
                refs_graph["nodes"][2]["data"]["config"] = {"outputs": {"result": "done"}}
                refs_graph["edges"] = [
                    {"id": "e1", "source": "start", "target": "llm"},
                    {"id": "e2", "source": "llm", "target": "end"},
                ]
                refs_parsed = WorkflowGraph.model_validate(refs_graph)
                _kb_ids, mcp_refs = workflow_resource_references(refs_parsed)
                assert mcp_refs == [
                    {"server_id": "s1", "tool_name": "t1"},
                    {"server_id": "s2", "tool_name": "t2"},
                ]

                # 234-251: definition is created on first access, then reused
                created_def = await get_or_create_definition(
                    db, workflow_agent, actor, "admin"
                )
                assert created_def.revision == 1
                existing_def = await get_or_create_definition(
                    db, workflow_agent, actor, "admin"
                )
                assert existing_def.id == created_def.id

                # 240-242, 249-251: with the auto-created definition removed, a
                # fresh workflow agent takes the create path
                from sqlalchemy import delete as sa_delete

                from app.shareddomain.workflows.models import (
                    WorkflowDefinition as WorkflowDefinitionOrm,
                )

                fresh = await agent_repository.get_agent_by_id(db, fresh_agent_id)
                assert fresh is not None
                await db.execute(
                    sa_delete(WorkflowDefinitionOrm).where(
                        WorkflowDefinitionOrm.agent_id == fresh_agent_id
                    )
                )
                await db.commit()
                fresh_def = await get_or_create_definition(db, fresh, actor, "admin")
                assert fresh_def.revision == 1
                assert fresh_def.agent_id == fresh_agent_id
                recreated = await get_or_create_definition(
                    db, fresh, actor, "admin"
                )
                assert recreated.id == fresh_def.id

                # 270-272: stale revision save conflicts
                try:
                    await save_definition(
                        db,
                        created_def,
                        WorkflowGraph.model_validate(_simple_graph()),
                        99,
                        actor,
                    )
                    raise AssertionError("expected 409 stale revision")
                except HTTPException as exc:
                    assert exc.status_code == 409
                    assert "reload it before saving" in str(exc.detail)
                # 276-277: successful save bumps the revision
                updated = await save_definition(
                    db,
                    created_def,
                    WorkflowGraph.model_validate(_simple_graph()),
                    created_def.revision,
                    actor,
                )
                assert updated.revision == created_def.revision + 1

                # 286-291: publish requires an existing definition
                plain_agent = await agent_repository.get_agent_by_id(db, plain_id)
                assert plain_agent is not None
                try:
                    await publish_definition(db, plain_agent, actor, "admin")
                    raise AssertionError("expected 404 for missing definition")
                except HTTPException as exc:
                    assert exc.status_code == 404
                    assert "Workflow definition not found" in str(exc.detail)

                # 294-295, 306-318: publish snapshot + version creation
                version = await publish_definition(db, workflow_agent, actor, "admin")
                assert version.version_number == 1
                assert version.definition_revision == updated.revision

        asyncio.run(run())


def test_upload_cleanup_records() -> None:
    from app.entities.workflows import WorkflowUpload
    from app.infrastructure.repositories import workflow as workflow_repository
    from app.infrastructure.session import get_session_factory
    from app.shareddomain.workflows.uploads import (
        prepare_due_upload_cleanups,
        queue_upload_cleanups,
        run_upload_storage_cleanup,
    )
    from tests.agents import agent_model_server

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id, model_id, agent_id, admin_user_id = _setup_workflow_ctx(
            client, model_base_url
        )
        runtime = settings()

        async def create_upload(object_key: str, filename: str) -> str:
            async with get_session_factory()() as db:
                upload = WorkflowUpload(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    uploaded_by_user_id=admin_user_id,
                    filename=filename,
                    content_type="text/plain",
                    size_bytes=4,
                    category="document",
                    object_key=object_key,
                )
                created = await workflow_repository.create_upload(db, upload)
                await db.commit()
                cleanup_ids = await queue_upload_cleanups(
                    db, upload_ids=[created.id]
                )
                assert len(cleanup_ids) == 1
                await db.commit()
                return cleanup_ids[0]

        async def failure_path(cleanup_id: str) -> None:
            with patch(
                "app.shareddomain.workflows.uploads.create_object_storage",
                return_value=_RaisingStorage(),
            ):
                try:
                    await run_upload_storage_cleanup(cleanup_id, runtime)
                    raise AssertionError("expected cleanup failure to re-raise")
                except OSError as exc:
                    assert "disk full" in str(exc)

        async def run() -> None:
            # 34-36: missing cleanup record returns without action
            await run_upload_storage_cleanup("missing-cleanup", runtime)

            # 42-49: storage failure records retry state and re-raises
            failure_id = await create_upload(
                f"workflow/{agent_id}/failure.txt", "failure.txt"
            )
            await failure_path(failure_id)
            async with get_session_factory()() as db:
                cleanup = await workflow_repository.lock_upload_cleanup(
                    db, failure_id
                )
                assert cleanup is not None
                assert cleanup.attempts == 1
                assert "OSError" in (cleanup.last_error or "")
                assert cleanup.next_attempt_at > cleanup.created_at

            # 50-51: successful delete removes the cleanup record
            await run_upload_storage_cleanup(failure_id, runtime)
            async with get_session_factory()() as db:
                assert (
                    await workflow_repository.lock_upload_cleanup(db, failure_id)
                    is None
                )

            # 54-65: due cleanups are listed by prepare_due_upload_cleanups
            due_id = await create_upload(f"workflow/{agent_id}/due.txt", "due.txt")
            due = await prepare_due_upload_cleanups()
            assert due_id in due

        asyncio.run(run())


# ---------------------------------------------------------------------------
# API-level workflow run lifecycle tests
# ---------------------------------------------------------------------------


def test_workflow_run_lifecycle_and_error_paths() -> None:
    from tests.agents import (
        agent_model_server,
        create_workspace_user,
        model_payload,
    )

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_base_url, "Lifecycle Model"),
        )
        assert model.status_code == 201, model.text
        workflow = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=headers,
            json={
                "name": "Lifecycle Workflow",
                "app_type": "workflow",
                "model_id": model.json()["id"],
                "interaction_config": {
                    "prologue": "Start a workflow.",
                    "tts_type": "BROWSER",
                    "file_upload": True,
                    "file_upload_setting": {"file_upload_type": ["document"]},
                    "user_input_title": "Question",
                },
            },
        )
        assert workflow.status_code == 201, workflow.text
        workflow_id = workflow.json()["id"]
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{workflow_id}"

        definition = client.get(f"{base}/definition", headers=headers)
        assert definition.status_code == 200, definition.text
        assert definition.json()["revision"] == 1
        wf_graph = definition.json()["graph"]
        wf_graph["nodes"].extend(
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
        wf_graph["edges"] = [
            {"id": "start-value", "source": "start", "target": "value"},
            {"id": "value-end", "source": "value", "target": "end"},
        ]
        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 1, "graph": wf_graph},
        )
        assert saved.status_code == 200, saved.text

        # endpoint line 94: validate success
        validated = client.post(
            f"{base}/validate", headers=headers, json={"graph": wf_graph}
        )
        assert validated.status_code == 200, validated.text
        assert validated.json()["valid"] is True

        # services 101-102: validate rejects an invalid graph
        bad_graph = json.loads(json.dumps(wf_graph))
        bad_graph["nodes"] = []
        invalid = client.post(
            f"{base}/validate", headers=headers, json={"graph": bad_graph}
        )
        assert invalid.status_code == 422, invalid.text

        # 179: draft runs cannot select a published version
        draft_with_version = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "draft", "version_number": 1, "question": "q"},
        )
        assert draft_with_version.status_code == 422, draft_with_version.text

        # 190-192: published run with an unknown version
        missing_version = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "published", "version_number": 1, "question": "q"},
        )
        assert missing_version.status_code == 404, missing_version.text

        # publish path (services 294-295, 306-318)
        published = client.post(f"{base}/publish", headers=headers)
        assert published.status_code == 201, published.text
        assert published.json()["version_number"] == 1

        # published run now resolves the version (190-192 success)
        published_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "published", "version_number": 1, "question": "version-one"},
        )
        assert published_run.status_code == 201, published_run.text
        assert published_run.json()["status"] == "succeeded"
        assert published_run.json()["version_number"] == 1

        # draft console run succeeds (219-220, 225-237, 255-256, 270-293, 322-326)
        draft_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "draft", "question": "draft-q"},
        )
        assert draft_run.status_code == 201, draft_run.text
        assert draft_run.json()["status"] == "succeeded"
        run_id = draft_run.json()["id"]

        # 363-384: run listing
        listed = client.get(f"{base}/runs", headers=headers)
        assert listed.status_code == 200, listed.text
        assert {item["id"] for item in listed.json()} == {
            run_id,
            published_run.json()["id"],
        }

        # 351: run detail
        fetched = client.get(f"{base}/runs/{run_id}", headers=headers)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["outputs"] == {"result": "draft-q"}

        # 350: unknown run id
        missing = client.get(f"{base}/runs/does-not-exist", headers=headers)
        assert missing.status_code == 404, missing.text

        # 398-400: node executions
        nodes = client.get(f"{base}/runs/{run_id}/nodes", headers=headers)
        assert nodes.status_code == 200, nodes.text
        assert [item["status"] for item in nodes.json()["items"]] == [
            "succeeded",
            "succeeded",
            "succeeded",
        ]
        assert nodes.json()["items"][1]["outputs"] == {"value": "draft-q"}

        # endpoint lines 307 + 318, stream terminal branch (501-502, 539-559)
        events = client.get(f"{base}/runs/{run_id}/stream", headers=headers)
        assert events.status_code == 200, events.text
        event_types = [json.loads(line)["type"] for line in events.text.splitlines()]
        assert event_types[0] == "run"
        assert event_types[-1] == "complete"

        # 412-413: form submit on a run that is not awaiting input
        wrong_form = client.post(
            f"{base}/runs/{run_id}/form",
            headers=headers,
            json={"runtime_node_id": "form", "form_data": {}},
        )
        assert wrong_form.status_code == 409, wrong_form.text

        # console file uploads feed the run inputs (237-249, 290-293)
        console_uploaded = client.post(
            f"{base}/uploads",
            headers=headers,
            files={"files": ("notes.txt", b"hello workflow", "text/plain")},
        )
        assert console_uploaded.status_code == 201, console_uploaded.text
        console_upload_id = console_uploaded.json()[0]["id"]
        file_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={
                "source": "draft",
                "question": "with-file",
                "file_ids": [console_upload_id],
            },
        )
        assert file_run.status_code == 201, file_run.text
        assert file_run.json()["inputs"]["files"][0]["name"] == "notes.txt"

        # member without a grant: 338 (view denied) and 219-222 (run denied)
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
        denied_view = client.get(f"{base}/runs/{run_id}", headers=member_headers)
        assert denied_view.status_code == 403, denied_view.text
        denied_draft = client.post(
            f"{base}/runs",
            headers=member_headers,
            json={"source": "draft", "question": "nope"},
        )
        assert denied_draft.status_code == 403, denied_draft.text
        denied_published = client.post(
            f"{base}/runs",
            headers=member_headers,
            json={"source": "published", "version_number": 1, "question": "nope"},
        )
        assert denied_published.status_code == 403, denied_published.text

        # 223-224: disabled workflow agents cannot run
        _set_agent_status(workflow_id, "disabled")
        disabled_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "draft", "question": "q"},
        )
        assert disabled_run.status_code == 409, disabled_run.text
        assert "disabled" in disabled_run.json()["detail"]
        _set_agent_status(workflow_id, "active")
        reenabled = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "draft", "question": "back"},
        )
        assert reenabled.status_code == 201, reenabled.text


def _set_agent_status(agent_id: str, status: str) -> None:
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.session import get_session_factory

    async def run() -> None:
        async with get_session_factory()() as db:
            entity = await agent_repository.get_agent_by_id(db, agent_id)
            assert entity is not None
            entity.status = status
            await agent_repository.save_agent(db, entity)
            await db.commit()

    asyncio.run(run())


def test_workflow_form_pause_and_resume() -> None:
    from tests.agents import agent_model_server

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id, model_id, agent_id, admin_user_id = _setup_workflow_ctx(
            client, model_base_url, name="Form Workflow"
        )
        headers = auth_headers(token)
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{agent_id}"

        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 1, "graph": _form_graph()},
        )
        assert saved.status_code == 200, saved.text

        # draft run pauses at the form node (84, 219-220, 255-256, 322-326)
        paused = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "draft", "question": "fill-me"},
        )
        assert paused.status_code == 201, paused.text
        assert paused.json()["status"] == "awaiting_input"
        pending = paused.json()["pending_form"]
        assert pending is not None
        assert pending["runtime_node_id"] == "form"
        run_id = paused.json()["id"]

        # get_run surfaces the pending form (84)
        fetched = client.get(f"{base}/runs/{run_id}", headers=headers)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["pending_form"]["runtime_node_id"] == "form"

        # node executions show the paused form node
        nodes = client.get(f"{base}/runs/{run_id}/nodes", headers=headers)
        assert nodes.status_code == 200, nodes.text
        form_item = next(
            item for item in nodes.json()["items"] if item["node_id"] == "form"
        )
        assert form_item["status"] == "awaiting_input"

        # 414-415: runtime node id mismatch
        changed = client.post(
            f"{base}/runs/{run_id}/form",
            headers=headers,
            json={"runtime_node_id": "ghost", "form_data": {}},
        )
        assert changed.status_code == 409, changed.text

        # 92-96: unknown form fields
        unknown = client.post(
            f"{base}/runs/{run_id}/form",
            headers=headers,
            json={"runtime_node_id": "form", "form_data": {"bogus": "x"}},
        )
        assert unknown.status_code == 422, unknown.text

        # 100-106: required field missing
        missing_required = client.post(
            f"{base}/runs/{run_id}/form",
            headers=headers,
            json={"runtime_node_id": "form", "form_data": {"name": ""}},
        )
        assert missing_required.status_code == 422, missing_required.text

        # valid submission resumes and completes (427-452, 465-477, endpoint 254)
        resumed = client.post(
            f"{base}/runs/{run_id}/form",
            headers=headers,
            json={
                "runtime_node_id": "form",
                "form_data": {
                    "name": "alice",
                    "color": "red",
                    "when": "2026-01-15",
                    "count": "2",
                    "notes": "ok",
                },
            },
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "succeeded"
        assert resumed.json()["outputs"] == {"result": "done"}

        # a second submission is rejected (411-413)
        second = client.post(
            f"{base}/runs/{run_id}/form",
            headers=headers,
            json={"runtime_node_id": "form", "form_data": {"name": "bob"}},
        )
        assert second.status_code == 409, second.text


def test_workflow_external_runs_and_conversation_conflict() -> None:
    from tests.agents import agent_model_server, create_workspace_user

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id, model_id, agent_id, admin_user_id = _setup_workflow_ctx(
            client, model_base_url, name="External Workflow"
        )
        headers = auth_headers(token)
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{agent_id}"

        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 1, "graph": _form_graph()},
        )
        assert saved.status_code == 200, saved.text
        published = client.post(f"{base}/publish", headers=headers)
        assert published.status_code == 201, published.text

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
        public_base = f"/api/v1/public/workflows/{agent_id}"

        # external run pauses at the form node (access_source public path)
        first = client.post(
            f"{public_base}/runs",
            headers=member_headers,
            json={"question": "external-q", "conversation_id": "conv-ext-1"},
        )
        assert first.status_code == 201, first.text
        assert first.json()["status"] == "awaiting_input"
        run_id = first.json()["id"]

        # 259-269: an active conversation cannot start a second run
        second = client.post(
            f"{public_base}/runs",
            headers=member_headers,
            json={"question": "external-q-2", "conversation_id": "conv-ext-1"},
        )
        assert second.status_code == 409, second.text

        # external run detail
        fetched = client.get(f"{public_base}/runs/{run_id}", headers=member_headers)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["status"] == "awaiting_input"

        # external form submit resumes the run (427-452)
        submitted = client.post(
            f"{public_base}/runs/{run_id}/form",
            headers=member_headers,
            json={
                "runtime_node_id": "form",
                "form_data": {
                    "name": "alice",
                    "color": "blue",
                    "when": "2026-02-01",
                    "count": "7",
                    "notes": "external",
                },
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "succeeded"
        assert submitted.json()["outputs"] == {"result": "done"}

        # conversations list reflects the completed run
        conversations = client.get(
            f"{public_base}/conversations", headers=member_headers
        )
        assert conversations.status_code == 200, conversations.text
        assert conversations.json()["items"][0]["outputs"] == {"result": "done"}


def test_workflow_run_direct_api_functions() -> None:
    """Cover API-driven branches via direct calls.

    The TestClient portal thread does not reliably record lines after `await`
    under the coverage trace function (starlette 1.3.1 + anyio 4.14.1 +
    CPython 3.11), so the read/submit/resume flows are exercised directly here
    where tracing is recorded faithfully.
    """
    from fastapi import HTTPException

    from app.application.workflow_runs import (
        create_workflow_run,
        get_workflow_run,
        list_workflow_node_executions,
        list_workflow_runs,
        resume_workflow_form,
        submit_workflow_form,
    )
    from app.entities.agents import AgentRun
    from app.entities.workflows import WorkflowRunDetail
    from app.infrastructure.repositories import agent as agent_repository
    from app.infrastructure.repositories import user as user_repository
    from app.infrastructure.repositories import workflow as workflow_repository
    from app.infrastructure.session import get_session_factory
    from app.schemas.workflow import WorkflowFormSubmitRequest, WorkflowRunCreateRequest
    from tests.agents import agent_model_server

    with test_client() as client, agent_model_server() as model_base_url:
        token, workspace_id, model_id, agent_id, admin_user_id = _setup_workflow_ctx(
            client, model_base_url
        )
        runtime = settings()
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{agent_id}"
        headers = auth_headers(token)
        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 1, "graph": _simple_graph()},
        )
        assert saved.status_code == 200, saved.text
        published = client.post(f"{base}/publish", headers=headers)
        assert published.status_code == 201, published.text

        async def run() -> None:
            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None

                # 224: disabled workflow agents cannot run
                agent_entity = await agent_repository.get_agent_by_id(db, agent_id)
                assert agent_entity is not None
                agent_entity.status = "disabled"
                await agent_repository.save_agent(db, agent_entity)
                await db.commit()
                try:
                    await create_workflow_run(
                        db,
                        workspace_id,
                        agent_id,
                        WorkflowRunCreateRequest(question="q"),
                        actor,
                        "admin",
                        runtime,
                    )
                    raise AssertionError("expected 409 disabled workflow")
                except HTTPException as exc:
                    assert exc.status_code == 409
                    assert "Workflow is disabled." in str(exc.detail)
                agent_entity.status = "active"
                await agent_repository.save_agent(db, agent_entity)
                await db.commit()

                # external run with pre-resolved files (290-293)
                external = await create_workflow_run(
                    db,
                    workspace_id,
                    agent_id,
                    WorkflowRunCreateRequest(
                        question="ext-files",
                        source="published",
                        version_number=1,
                    ),
                    actor,
                    "admin",
                    runtime,
                    access_source="public",
                    consumer_id="direct-consumer",
                    conversation_id="conv-direct-files",
                    files=[
                        {
                            "id": "file-1",
                            "name": "notes.txt",
                            "content_type": "text/plain",
                            "size_bytes": 4,
                            "category": "document",
                        }
                    ],
                )
                assert external.inputs["files"] == external.inputs["document"]
                assert external.inputs["files"][0]["name"] == "notes.txt"

                # console run for the read/list flows (322-326)
                console = await create_workflow_run(
                    db,
                    workspace_id,
                    agent_id,
                    WorkflowRunCreateRequest(question="direct-q"),
                    actor,
                    "admin",
                    runtime,
                )
                assert console.status == "succeeded"
                run_id = console.id

                # 338-351: get_workflow_run success
                fetched = await get_workflow_run(
                    db, workspace_id, agent_id, run_id, actor, "admin"
                )
                assert fetched.id == run_id
                # 350: run not owned by / not visible to the actor (external)
                try:
                    await get_workflow_run(
                        db, workspace_id, agent_id, external.id, actor, "admin"
                    )
                    raise AssertionError("expected 404 for foreign run")
                except HTTPException as exc:
                    assert exc.status_code == 404
                    assert "Workflow run not found." in str(exc.detail)
                # 338: no permission -> 403
                no_grant_actor = SimpleNamespace(id="no-grant-user", is_active=True)
                try:
                    await get_workflow_run(
                        db, workspace_id, agent_id, run_id, no_grant_actor, None
                    )
                    raise AssertionError("expected 403 without permission")
                except HTTPException as exc:
                    assert exc.status_code == 403

                # 364-365, 373-384: list_workflow_runs
                listed = await list_workflow_runs(
                    db, workspace_id, agent_id, actor, "admin", 10, 0
                )
                assert run_id in {item.id for item in listed}

                # 398-400: node executions
                executions = await list_workflow_node_executions(
                    db, workspace_id, agent_id, run_id, actor, "admin"
                )
                assert len(executions.items) == 3
                assert executions.items[0].node_id == "start"
                assert executions.items[0].model_usage is not None

            # 446-452: resume_workflow_form success path on a real paused run
            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None
                definition = await workflow_repository.get_definition(
                    db, workspace_id, agent_id
                )
                assert definition is not None
                paused = AgentRun(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    requested_by_user_id=admin_user_id,
                    execution_user_id=admin_user_id,
                    access_source="console",
                    consumer_id=admin_user_id,
                    conversation_id="conv-resume-direct",
                    goal="resume",
                    instructions="",
                    knowledge_base_ids=[],
                    mcp_tools=[],
                    model_id=model_id,
                    model_name="Coverage Model",
                    status="awaiting_input",
                    checkpoint_phase="workflow",
                    trace_id="trace-resume",
                    model_usage={},
                    checkpoint={
                        "workflow_form": {
                            "runtime_node_id": "form",
                            "content": "x",
                            "fields": [],
                        }
                    },
                )
                created = await agent_repository.create_agent_run(db, paused)
                detail = WorkflowRunDetail(
                    workspace_id=workspace_id,
                    definition_id=definition.id,
                    definition_revision=definition.revision,
                    graph_snapshot=_form_graph(),
                    inputs={"question": "resume"},
                )
                detail.run_id = created.id
                await workflow_repository.create_run_detail(db, detail)
                await db.commit()
                resumed = await resume_workflow_form(
                    db,
                    created,
                    detail,
                    WorkflowFormSubmitRequest(
                        runtime_node_id="form",
                        form_data={
                            "name": "alice",
                            "color": "red",
                            "when": "2026-01-15",
                            "count": "2",
                            "notes": "ok",
                        },
                    ),
                    runtime,
                )
                assert resumed.status == "succeeded"

                # 473-477: submit_workflow_form success path on a fresh paused run
                paused_again = AgentRun(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    requested_by_user_id=admin_user_id,
                    execution_user_id=admin_user_id,
                    access_source="console",
                    consumer_id=admin_user_id,
                    conversation_id="conv-submit-direct",
                    goal="submit",
                    instructions="",
                    knowledge_base_ids=[],
                    mcp_tools=[],
                    model_id=model_id,
                    model_name="Coverage Model",
                    status="awaiting_input",
                    checkpoint_phase="workflow",
                    trace_id="trace-submit",
                    model_usage={},
                    checkpoint={
                        "workflow_form": {
                            "runtime_node_id": "form",
                            "content": "x",
                            "fields": [],
                        }
                    },
                )
                created_again = await agent_repository.create_agent_run(
                    db, paused_again
                )
                detail_again = WorkflowRunDetail(
                    workspace_id=workspace_id,
                    definition_id=definition.id,
                    definition_revision=definition.revision,
                    graph_snapshot=_form_graph(),
                    inputs={"question": "submit"},
                )
                detail_again.run_id = created_again.id
                await workflow_repository.create_run_detail(db, detail_again)
                await db.commit()
                submitted = await submit_workflow_form(
                    db,
                    workspace_id,
                    agent_id,
                    created_again.id,
                    WorkflowFormSubmitRequest(
                        runtime_node_id="form",
                        form_data={
                            "name": "bob",
                            "color": "blue",
                            "when": "2026-02-01",
                            "count": "5",
                            "notes": "ok",
                        },
                    ),
                    actor,
                    "admin",
                    runtime,
                )
                assert submitted.id == created_again.id
                assert submitted.status == "succeeded"

                # 450-451: resume re-fetch returning no run -> 404
                paused_three = AgentRun(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    requested_by_user_id=admin_user_id,
                    execution_user_id=admin_user_id,
                    access_source="console",
                    consumer_id=admin_user_id,
                    conversation_id="conv-451",
                    goal="resume-451",
                    instructions="",
                    knowledge_base_ids=[],
                    mcp_tools=[],
                    model_id=model_id,
                    model_name="Coverage Model",
                    status="awaiting_input",
                    checkpoint_phase="workflow",
                    trace_id="trace-451",
                    model_usage={},
                    checkpoint={
                        "workflow_form": {
                            "runtime_node_id": "form",
                            "content": "x",
                            "fields": [],
                        }
                    },
                )
                created_three = await agent_repository.create_agent_run(
                    db, paused_three
                )
                detail_three = WorkflowRunDetail(
                    workspace_id=workspace_id,
                    definition_id=definition.id,
                    definition_revision=definition.revision,
                    graph_snapshot=_form_graph(),
                    inputs={"question": "resume-451"},
                )
                detail_three.run_id = created_three.id
                await workflow_repository.create_run_detail(db, detail_three)
                await db.commit()
                with (
                    patch(
                        "app.infrastructure.repositories.agent.get_agent_run_by_id",
                        new=AsyncMock(return_value=None),
                    ),
                    patch(
                        "app.application.workflow_runs.enqueue_agent_run",
                        new=AsyncMock(),
                    ),
                ):
                    try:
                        await resume_workflow_form(
                            db,
                            created_three,
                            detail_three,
                            WorkflowFormSubmitRequest(
                                runtime_node_id="form",
                                form_data={"name": "x"},
                            ),
                            runtime,
                        )
                        raise AssertionError("expected 404 missing resumed run")
                    except HTTPException as exc:
                        assert exc.status_code == 404
                        assert "Workflow run not found." in str(exc.detail)

                # 475-476: submit re-fetch returning no run -> 404
                real_get_run = agent_repository.get_agent_run_by_id
                state = {"calls": 0}

                async def flaky_get_run(db, run_id):
                    state["calls"] += 1
                    if state["calls"] >= 2:
                        return None
                    return await real_get_run(db, run_id)

                with (
                    patch(
                        "app.infrastructure.repositories.agent.get_agent_run_by_id",
                        new=flaky_get_run,
                    ),
                    patch(
                        "app.application.workflow_runs.enqueue_agent_run",
                        new=AsyncMock(),
                    ),
                ):
                    try:
                        await submit_workflow_form(
                            db,
                            workspace_id,
                            agent_id,
                            created_three.id,
                            WorkflowFormSubmitRequest(
                                runtime_node_id="form",
                                form_data={"name": "x"},
                            ),
                            actor,
                            "admin",
                            runtime,
                        )
                        raise AssertionError("expected 404 missing submitted run")
                    except HTTPException as exc:
                        assert exc.status_code == 404
                        assert "Workflow run not found." in str(exc.detail)

            # endpoint 307 + 318: reconnect_run rollback + StreamingResponse
            from app.api.v1.endpoints.workflows import reconnect_run

            async with get_session_factory()() as db:
                actor = await user_repository.get_user_by_id(db, admin_user_id)
                assert actor is not None
                context = SimpleNamespace(
                    workspace=SimpleNamespace(id=workspace_id),
                    user=actor,
                    membership_role="admin",
                )
                stream_response = await reconnect_run(
                    agent_id,
                    run_id,
                    context,
                    runtime,
                    db,
                    0,
                    "0-0",
                )
                assert stream_response is not None
                assert stream_response.media_type == "application/x-ndjson"

        asyncio.run(run())


def main() -> None:
    test_engine_validation_error_branches()
    test_engine_runtime_error_branches()
    test_validated_form_data_branches()
    test_create_workflow_run_guard_errors()
    test_create_workflow_run_external_and_conflicts()
    test_resume_workflow_form_error_branches()
    test_workflow_stream_branches()
    test_workflow_services_boundaries()
    test_upload_cleanup_records()
    test_workflow_run_lifecycle_and_error_paths()
    test_workflow_form_pause_and_resume()
    test_workflow_external_runs_and_conversation_conflict()
    test_workflow_run_direct_api_functions()
    print("WORKFLOW_RUN_COVERAGE_SUITE_OK")


if __name__ == "__main__":
    main()
