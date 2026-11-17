"""Workflow Skills and MCP approval regressions using mocked capability ports."""

import asyncio
import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import tests.support  # noqa: F401
from langchain_core.messages import AIMessage
from tests.agents.agents import create_workspace_user
from tests.models.llm import model_payload, model_test_server
from tests.support import (
    activate_admin,
    activate_user,
    auth_headers,
    settings,
    test_client,
)

from app.application.workflows.runs.executor import run_durable_workflow_run
from app.domain.tools.catalog.service import reconcile_mcp_discovery
from app.entities.tools import McpServer, ToolSource
from app.infra.db.repositories.identity import users
from app.infra.db.repositories.tools import mcp as mcp_repository
from app.infra.db.repositories.tools import repository as tools
from app.infra.db.session import get_session_factory
from app.ports.mcp import McpCallResult


async def seed_mcp(workspace_id, access_sources=None):
    async with get_session_factory()() as db:
        actor = await users.get_active_user_by_username(db, "admin")
        server = await mcp_repository.create_mcp_server(
            db,
            McpServer(
                workspace_id=workspace_id,
                name="Workflow MCP",
                url="https://workflow.invalid/mcp",
                created_by_user_id=actor.id,
            ),
        )
        source = await tools.save_tool_source(
            db,
            ToolSource(
                workspace_id=workspace_id,
                mcp_server_id=server.id,
                kind="mcp",
                name=server.name,
                created_by_user_id=actor.id,
            ),
        )
        await reconcile_mcp_discovery(
            db,
            server,
            source,
            [
                {
                    "name": "lookup",
                    "description": "Fetch a record",
                    "input_schema": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"],
                    },
                }
            ],
        )
        tool = (await tools.list_tools_by_source(db, workspace_id, source.id))[0]
        policy = await tools.get_tool_policy(db, workspace_id, tool.id)
        assert policy.approval == "each_call" and policy.workflow_callable
        if access_sources:
            expected = policy.revision
            policy.revision += 1
            policy.allowed_access_sources = access_sources
            assert await tools.update_tool_policy_if_revision(db, policy, expected)
        await db.commit()
        return tool


class ScriptedModel:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0
        self.schemas = []

    def bind_tools(self, tools):
        self.schemas.append([item.name for item in tools])
        return self

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def call(name, arguments, identity):
    return AIMessage(
        content="",
        tool_calls=[{"id": identity, "name": name, "args": arguments}],
        usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
    )


def workflow_graph(config):
    return {
        "nodes": [
            {
                "id": key,
                "position": {"x": index * 350, "y": 0},
                "data": {"type": kind, "title": key, "config": data},
            }
            for index, (key, kind, data) in enumerate(
                [
                    ("start", "start", {}),
                    (
                        "llm",
                        "llm",
                        {"prompt": "{{start.question}}", "is_result": False, **config},
                    ),
                    ("end", "end", {"outputs": {"result": "{{llm.text}}"}}),
                ]
            )
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "llm"},
            {"id": "b", "source": "llm", "target": "end"},
        ],
    }


def test_workflow_skill_script_mcp_approval_and_resume():
    with test_client() as client, model_test_server() as model_url:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model_response = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_url),
        )
        assert model_response.status_code == 201, model_response.text
        model_id = model_response.json()["id"]
        skill_url = f"/api/v1/workspaces/{workspace_id}/agent-skills"
        created = client.post(
            skill_url,
            headers=headers,
            json={
                "name": "Workflow script",
                "description": "Run the pinned calculation",
                "definition": {
                    "instructions": "Use scripts/calculate.py with JSON input.",
                    "files": {
                        "scripts/calculate.py": base64.b64encode(
                            b"print('calculated')"
                        ).decode()
                    },
                },
            },
        )
        assert created.status_code == 201, created.text
        skill = created.json()
        published = client.post(f"{skill_url}/{skill['id']}/publish", headers=headers)
        assert published.status_code == 200, published.text
        skill_ref = {"skill_id": skill["id"], "version_id": published.json()["id"]}
        remote = asyncio.run(seed_mcp(workspace_id, ["console", "public", "api"]))
        reference = {"tool_id": remote.id, "version_id": remote.current_version_id}
        created_workflow = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=headers,
            json={
                "name": "Capabilities workflow",
                "app_type": "workflow",
                "model_id": model_id,
            },
        )
        assert created_workflow.status_code == 201, created_workflow.text
        workflow_id = created_workflow.json()["id"]
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{workflow_id}"
        definition = client.get(f"{base}/definition", headers=headers).json()
        graph = workflow_graph(
            {
                "tools": [reference],
                "skills": [skill_ref],
                "capability_tools": [{"tool_id": "forged", "version_id": "forged"}],
            }
        )
        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": definition["revision"], "graph": graph},
        )
        assert saved.status_code == 200, saved.text
        derived = saved.json()["graph"]["nodes"][1]["data"]["config"][
            "capability_tools"
        ]
        assert len(derived) == 3 and all(
            item["tool_id"] != "forged" for item in derived
        )
        publication = client.post(f"{base}/publish", headers=headers)
        assert publication.status_code == 201, publication.text

        replies = ScriptedModel(
            [
                call("load_skill", {"version_id": skill_ref["version_id"]}, "load"),
                call(
                    "run_skill_script",
                    {
                        "version_id": skill_ref["version_id"],
                        "path": "scripts/calculate.py",
                        "inputs": {"value": 3},
                        "filename": "calculation.txt",
                    },
                    "script",
                ),
                call(remote.function_name, {"id": "123"}, "mcp"),
                AIMessage(
                    content="calculated and fetched",
                    usage_metadata={
                        "input_tokens": 2,
                        "output_tokens": 1,
                        "total_tokens": 3,
                    },
                ),
            ]
        )
        requests = []

        async def script_execute(request, **kwargs):
            assert request["script"] == "scripts/calculate.py"
            assert (
                base64.b64decode(request["files"]["scripts/calculate.py"])
                == b"print('calculated')"
            )
            assert "network_domains" not in request
            requests.append(request)
            content = b"calculated"
            return {
                "ok": True,
                "stdout": "calculated",
                "stderr": "",
                "exit_code": 0,
                "artifact": {
                    "format": "txt",
                    "filename": "calculation.txt",
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "content_base64": base64.b64encode(content).decode(),
                },
            }

        platform = SimpleNamespace(execute=script_execute)
        remote_call = AsyncMock(
            return_value=McpCallResult(content=[{"type": "text", "text": "record"}])
        )
        with (
            patch(
                "app.application.workflows.runs.service.enqueue_agent_run",
                new=AsyncMock(),
            ),
            patch(
                "app.application.agents.runs.service.enqueue_prepared_agent_run",
                new=AsyncMock(),
            ),
            patch(
                "app.application.workflows.nodes.executor.build_chat_model",
                return_value=replies,
            ),
            patch(
                "app.application.agent_skills.scripts.build_execution_platform",
                return_value=platform,
            ),
            patch(
                "app.application.tools.runtime.adapters.mcp.call_mcp_tool",
                new=remote_call,
            ),
        ):
            queued = client.post(
                f"{base}/runs",
                headers=headers,
                json={"source": "published", "question": "Run capabilities"},
            )
            assert queued.status_code == 201, queued.text
            run_id = queued.json()["id"]
            asyncio.run(
                run_durable_workflow_run(
                    run_id, settings(), "workflow-cap-1", generation="unified"
                )
            )
            paused = client.get(f"{base}/runs/{run_id}", headers=headers)
            assert paused.status_code == 200, paused.text
            assert paused.json()["status"] == "awaiting_approval", paused.text
            assert (
                len(requests) == 1
                and replies.calls == 3
                and remote_call.await_count == 0
            )
            pending = next(
                item
                for item in paused.json()["tool_calls"]
                if item["status"] == "awaiting_approval"
            )
            assert pending["call_id"].startswith("llm:llm:")
            assert pending["arguments"] == {"id": "123"}
            executions = client.get(f"{base}/runs/{run_id}/nodes", headers=headers)
            assert executions.status_code == 200, executions.text
            approved = client.post(
                f"{base}/runs/{run_id}/tool-calls/{pending['call_id']}/approval",
                headers=headers,
                json={"approve": True},
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "queued"
            asyncio.run(
                run_durable_workflow_run(
                    run_id, settings(), "workflow-cap-2", generation="unified"
                )
            )
            finished = client.get(f"{base}/runs/{run_id}", headers=headers)
            assert finished.json()["status"] == "succeeded", finished.text
            assert finished.json()["outputs"]["result"] == "calculated and fetched"
            assert (
                len(requests) == 1
                and replies.calls == 4
                and remote_call.await_count == 1
            )
            assert {item["status"] for item in finished.json()["tool_calls"]} == {
                "succeeded"
            }
            assert finished.json()["token_usage"] == 12

            async def download_link():
                async with get_session_factory()() as db:
                    invocations = await tools.list_tool_invocations(
                        db, workspace_id, run_id
                    )
                    scripted = next(
                        item
                        for item in invocations
                        if item.policy_snapshot["tool_snapshot"]["function_name"]
                        == "run_skill_script"
                    )
                    return scripted.result_data["artifacts"][0]["download_url"]

            downloaded = client.get(asyncio.run(download_link()))
            assert downloaded.status_code == 200 and downloaded.content == b"calculated"

            # Public consumption keeps approvals scoped to that consumer and source.
            public = f"/api/v1/public/workflows/{workflow_id}"
            replies.responses.extend(
                [
                    call(remote.function_name, {"id": "public"}, "public-call"),
                    AIMessage(content="declined"),
                ]
            )
            public_run = client.post(
                f"{public}/runs", headers=headers, json={"question": "Public approval"}
            )
            assert public_run.status_code == 201, public_run.text
            public_id = public_run.json()["id"]
            asyncio.run(
                run_durable_workflow_run(
                    public_id, settings(), "workflow-public-1", generation="unified"
                )
            )
            paused_public = client.get(f"{public}/runs/{public_id}", headers=headers)
            assert paused_public.json()["status"] == "awaiting_approval", (
                paused_public.text
            )
            pending_public = next(
                item
                for item in paused_public.json()["tool_calls"]
                if item["status"] == "awaiting_approval"
            )
            public_call_id = pending_public["call_id"]
            wrong_source = client.post(
                f"{base}/runs/{public_id}/tool-calls/{public_call_id}/approval",
                headers=headers,
                json={"approve": True},
            )
            assert wrong_source.status_code == 404, wrong_source.text
            member_id, temporary_password = create_workspace_user(
                client, token, workspace_id
            )
            member_token = activate_user(
                client, "agent-member", temporary_password, "WorkflowMember@123!"
            )
            grant = client.put(
                f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}/permissions/{member_id}",
                headers=headers,
                json={"permission": "view"},
            )
            assert grant.status_code == 200, grant.text
            wrong_consumer = client.post(
                f"{public}/runs/{public_id}/tool-calls/{public_call_id}/approval",
                headers=auth_headers(member_token),
                json={"approve": True},
            )
            assert wrong_consumer.status_code == 404, wrong_consumer.text
            declined = client.post(
                f"{public}/runs/{public_id}/tool-calls/{public_call_id}/approval",
                headers=headers,
                json={"approve": False},
            )
            assert (
                declined.status_code == 200 and declined.json()["status"] == "queued"
            ), declined.text
            asyncio.run(
                run_durable_workflow_run(
                    public_id, settings(), "workflow-public-2", generation="unified"
                )
            )
            declined_run = client.get(f"{public}/runs/{public_id}", headers=headers)
            assert declined_run.json()["status"] == "succeeded", declined_run.text
            assert declined_run.json()["outputs"]["result"] == "declined"
            assert len(requests) == 1 and remote_call.await_count == 1

            # Machine consumers cannot bypass interactive approval.
            credential = client.post(
                f"/api/v1/workspaces/{workspace_id}/agents/{workflow_id}/api-credentials",
                headers=headers,
                json={"name": "Capability API"},
            )
            assert credential.status_code == 201, credential.text
            api_run = client.post(
                f"/api/v1/workflow-api/{workflow_id}/runs",
                headers=auth_headers(credential.json()["token"]),
                json={"question": "API approval"},
            )
            assert api_run.status_code == 409, api_run.text

            # Revocation after queuing must stop both scripts and MCP before execution.
            queued = client.post(
                f"{base}/runs",
                headers=headers,
                json={"source": "published", "question": "Revoked Skill"},
            )
            assert queued.status_code == 201, queued.text

            async def revoke():
                from app.infra.db.repositories.agent_skills import repository

                async with get_session_factory()() as db:
                    item = await repository.get_agent_skill(
                        db, workspace_id, skill["id"]
                    )
                    item.status = "disabled"
                    await repository.save_agent_skill(db, item)
                    await db.commit()

            asyncio.run(revoke())
            asyncio.run(
                run_durable_workflow_run(
                    queued.json()["id"],
                    settings(),
                    "workflow-cap-revoked",
                    generation="unified",
                )
            )
            failed = client.get(f"{base}/runs/{queued.json()['id']}", headers=headers)
            assert failed.json()["status"] == "failed", failed.text
            assert len(requests) == 1 and remote_call.await_count == 1


def test_parallel_mcp_nodes_approve_before_resuming():
    with test_client() as client, model_test_server() as model_url:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        model = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=headers,
            json=model_payload(model_url),
        )
        assert model.status_code == 201, model.text
        remote = asyncio.run(seed_mcp(workspace_id))
        reference = {"tool_id": remote.id, "version_id": remote.current_version_id}
        created = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=headers,
            json={
                "name": "Parallel approvals",
                "app_type": "workflow",
                "model_id": model.json()["id"],
            },
        )
        assert created.status_code == 201, created.text
        base = f"/api/v1/workspaces/{workspace_id}/workflows/{created.json()['id']}"
        definition = client.get(f"{base}/definition", headers=headers).json()
        graph = {
            "nodes": [
                {
                    "id": key,
                    "position": {"x": index * 350, "y": 0},
                    "data": {"type": kind, "title": key, "config": config},
                }
                for index, (key, kind, config) in enumerate(
                    [
                        ("start", "start", {}),
                        (
                            "one",
                            "tool",
                            {"tool": reference, "arguments": {"id": "one"}},
                        ),
                        (
                            "two",
                            "tool",
                            {"tool": reference, "arguments": {"id": "two"}},
                        ),
                        ("end", "end", {"outputs": {"result": "done"}}),
                    ]
                )
            ],
            "edges": [
                {"id": f"{source}-{target}", "source": source, "target": target}
                for source, target in [
                    ("start", "one"),
                    ("start", "two"),
                    ("one", "end"),
                    ("two", "end"),
                ]
            ],
        }
        saved = client.put(
            f"{base}/definition",
            headers=headers,
            json={"expected_revision": definition["revision"], "graph": graph},
        )
        assert saved.status_code == 200, saved.text
        assert client.post(f"{base}/publish", headers=headers).status_code == 201
        remote_call = AsyncMock(
            return_value=McpCallResult(content=[{"type": "text", "text": "record"}])
        )
        with (
            patch(
                "app.application.workflows.runs.service.enqueue_agent_run"
            ) as enqueue,
            patch(
                "app.application.agents.runs.service.enqueue_prepared_agent_run",
                new=AsyncMock(),
            ) as resume,
            patch(
                "app.application.tools.runtime.adapters.mcp.call_mcp_tool",
                new=remote_call,
            ),
        ):
            queued = client.post(
                f"{base}/runs",
                headers=headers,
                json={"source": "published", "question": "Both"},
            )
            assert queued.status_code == 201, queued.text
            run_id = queued.json()["id"]
            asyncio.run(
                run_durable_workflow_run(
                    run_id, settings(), "parallel-1", generation="unified"
                )
            )
            paused = client.get(f"{base}/runs/{run_id}", headers=headers)
            pending = paused.json()["tool_calls"]
            assert len(pending) == 2 and all(
                item["status"] == "awaiting_approval" for item in pending
            ), paused.text
            assert {item["call_id"] for item in pending} == {"one:direct", "two:direct"}
            enqueue.reset_mock()
            first = client.post(
                f"{base}/runs/{run_id}/tool-calls/{pending[0]['call_id']}/approval",
                headers=headers,
                json={"approve": True},
            )
            assert (
                first.status_code == 200
                and first.json()["status"] == "awaiting_approval"
            ), first.text
            enqueue.assert_not_called()
            resume.assert_not_called()
            second = client.post(
                f"{base}/runs/{run_id}/tool-calls/{pending[1]['call_id']}/approval",
                headers=headers,
                json={"approve": True},
            )
            assert second.status_code == 200 and second.json()["status"] == "queued", (
                second.text
            )
            asyncio.run(
                run_durable_workflow_run(
                    run_id, settings(), "parallel-2", generation="unified"
                )
            )
            finished = client.get(f"{base}/runs/{run_id}", headers=headers)
            assert finished.json()["status"] == "succeeded", finished.text
            assert remote_call.await_count == 2
            assert all(
                item["status"] == "succeeded" for item in finished.json()["tool_calls"]
            )


def test_workflow_capability_migration_preserves_approval_and_disabled_policies():
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/202611170005_workflow_capabilities.py"
    )
    spec = importlib.util.spec_from_file_location("workflow_capabilities", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    metadata = sa.MetaData()
    catalog = sa.Table(
        "tools",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("kind", sa.String),
        sa.Column("function_name", sa.String),
    )
    policies = sa.Table(
        "tool_policies",
        metadata,
        sa.Column("tool_id", sa.String, primary_key=True),
        sa.Column("approval", sa.String),
        sa.Column("workflow_callable", sa.Boolean),
        sa.Column("revision", sa.Integer),
        sa.Column("updated_at", sa.DateTime),
    )
    executions = sa.Table(
        "workflow_node_executions",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("status", sa.String),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded')",
            name="ck_workflow_node_executions_status",
        ),
    )
    with sa.create_engine("sqlite://").begin() as connection:
        metadata.create_all(connection)
        for tool_id, kind, function_name, approval, enabled in [
            ("remote", "mcp", "lookup", "each_call", False),
            ("disabled", "mcp", "delete", "disabled", False),
            ("bash", "builtin", "bash", "auto", False),
            ("guide", "builtin", "pptx_skill", "auto", False),
            ("runner", "builtin", "run_skill_script", "auto", False),
            ("installer", "builtin", "install_skill_dependencies", "each_call", False),
            ("image", "builtin", "generate_image", "each_call", False),
            ("existing", "mcp", "get", "auto", True),
        ]:
            connection.execute(
                catalog.insert(),
                {"id": tool_id, "kind": kind, "function_name": function_name},
            )
            connection.execute(
                policies.insert(),
                {
                    "tool_id": tool_id,
                    "approval": approval,
                    "workflow_callable": enabled,
                    "revision": 4,
                },
            )
        with patch.object(
            migration, "op", Operations(MigrationContext.configure(connection))
        ):
            migration.upgrade()
            migration.upgrade()
        rows = {
            item["tool_id"]: item
            for item in connection.execute(sa.select(policies)).mappings()
        }
        for identity in ("remote", "bash", "guide", "runner", "installer"):
            assert (
                rows[identity]["workflow_callable"] and rows[identity]["revision"] == 5
            )
        assert (
            rows["remote"]["approval"] == rows["installer"]["approval"] == "each_call"
        )
        assert (
            not rows["disabled"]["workflow_callable"]
            and rows["disabled"]["approval"] == "disabled"
            and rows["disabled"]["revision"] == 4
        )
        assert not rows["image"]["workflow_callable"] and rows["image"]["revision"] == 4
        assert rows["existing"]["revision"] == 4
        connection.execute(
            executions.insert(), {"id": "paused", "status": "awaiting_approval"}
        )


def main():
    test_workflow_skill_script_mcp_approval_and_resume()
    test_parallel_mcp_nodes_approve_before_resuming()
    test_workflow_capability_migration_preserves_approval_and_disabled_policies()
    print("WORKFLOW_CAPABILITIES_OK")


if __name__ == "__main__":
    main()
