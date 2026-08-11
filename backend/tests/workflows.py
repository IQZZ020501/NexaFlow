"""Workflow engine and API regression suite.

Run from ``backend/`` with ``uv run python -m tests.workflows``.
"""

import asyncio
from datetime import UTC, datetime, timedelta
import json

import tests.support  # noqa: F401

from app.shareddomain.workflows.engine import (
    NodeResult,
    NodeState,
    WorkflowEngine,
    WorkflowEngineError,
    WorkflowValidationError,
    validate_graph,
)
from tests.support import activate_admin, auth_headers, test_client


def graph(*, condition: bool = False) -> dict:
    nodes = [
        {
            "id": "start",
            "type": "workflow",
            "position": {"x": 0, "y": 0},
            "data": {
                "type": "start",
                "title": "Start",
                "config": {"inputs": [{"name": "input"}]},
            },
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
                            "left": "{{start.input}}",
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
                    "config": {"value": "{{start.input}}"},
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
    downstream["nodes"][0]["data"]["config"]["inputs"][0]["default"] = "{{value.value}}"
    try:
        validate_graph(downstream)
    except WorkflowValidationError:
        pass
    else:
        raise AssertionError("downstream workflow reference was accepted")


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
        try:
            await token_engine.run({"input": "x"}, execute)
        except WorkflowEngineError as exc:
            assert "token budget" in str(exc)
        else:
            raise AssertionError("token budget was not enforced")

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


def test_workflow_api_definition_publish_run_and_audit() -> None:
    from tests.agents import agent_model_server, model_payload

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
            },
        )
        assert workflow.status_code == 201, workflow.text
        workflow_id = workflow.json()["id"]
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{workflow_id}"

        definition = client.get(f"{base}/definition", headers=headers)
        assert definition.status_code == 200, definition.text
        assert definition.json()["revision"] == 1
        workflow_graph = definition.json()["graph"]
        workflow_graph["nodes"].insert(
            1,
            {
                "id": "value",
                "type": "workflow",
                "position": {"x": 270, "y": 180},
                "data": {
                    "type": "variable",
                    "title": "Value",
                    "config": {"value": "{{start.input}}"},
                },
            },
        )
        workflow_graph["nodes"][2]["data"]["config"] = {
            "outputs": {"result": "{{value.value}}"}
        }
        workflow_graph["edges"] = [
            {"id": "start-value", "source": "start", "target": "value"},
            {"id": "value-end", "source": "value", "target": "end"},
        ]
        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 1, "graph": workflow_graph},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["revision"] == 2
        conflict = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 1, "graph": workflow_graph},
        )
        assert conflict.status_code == 409, conflict.text

        published = client.post(f"{base}/publish", headers=headers)
        assert published.status_code == 201, published.text
        assert published.json()["version_number"] == 1
        assert published.json()["definition_revision"] == 2

        workflow_graph["nodes"][2]["data"]["config"] = {
            "outputs": {"result": "draft-two"}
        }
        next_draft = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": 2, "graph": workflow_graph},
        )
        assert next_draft.status_code == 200, next_draft.text
        assert next_draft.json()["revision"] == 3

        draft_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={"source": "draft", "inputs": {"input": "release-ready"}},
        )
        assert draft_run.status_code == 201, draft_run.text
        assert draft_run.json()["status"] == "succeeded"
        assert draft_run.json()["outputs"] == {"result": "draft-two"}
        run_id = draft_run.json()["id"]
        nodes = client.get(f"{base}/runs/{run_id}/nodes", headers=headers)
        assert nodes.status_code == 200, nodes.text
        assert [item["status"] for item in nodes.json()["items"]] == [
            "succeeded",
            "succeeded",
            "succeeded",
        ]
        assert nodes.json()["items"][1]["outputs"] == {"value": "release-ready"}

        events = client.get(f"{base}/runs/{run_id}/stream", headers=headers)
        assert events.status_code == 200, events.text
        event_types = [json.loads(line)["type"] for line in events.text.splitlines()]
        assert event_types[0] == "run"
        assert "workflow_node" in event_types
        assert event_types[-1] == "complete"

        published_run = client.post(
            f"{base}/runs",
            headers=headers,
            json={
                "source": "published",
                "version_number": 1,
                "inputs": {"input": "version-one"},
            },
        )
        assert published_run.status_code == 201, published_run.text
        assert published_run.json()["status"] == "succeeded"
        assert published_run.json()["outputs"] == {"result": "version-one"}
        assert published_run.json()["version_number"] == 1

        versions = client.get(f"{base}/versions", headers=headers)
        assert versions.status_code == 200, versions.text
        assert [item["version_number"] for item in versions.json()["items"]] == [1]
        restored = client.post(f"{base}/versions/1/restore", headers=headers)
        assert restored.status_code == 200, restored.text
        assert restored.json()["revision"] == 4
        assert restored.json()["graph"]["nodes"][2]["data"]["config"] == {
            "outputs": {"result": "{{value.value}}"}
        }

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
        assert credentials.status_code == 409, credentials.text


def main() -> None:
    test_workflow_validation_rejects_cycles_and_downstream_references()
    test_workflow_engine_runs_branch_and_join_deterministically()
    test_workflow_engine_enforces_step_and_token_budgets()
    test_workflow_engine_propagates_worker_cancellation()
    test_workflow_api_definition_publish_run_and_audit()
    print("WORKFLOW_SUITE_OK")


if __name__ == "__main__":
    main()
