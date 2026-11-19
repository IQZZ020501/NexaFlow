"""Conversation MCP approval against the real invocation ledger and ACL checks."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
from tests.agents.agents import agent_model_server, agents_url, model_payload
from tests.agents.evaluation import ScriptedModel, answer_message
from tests.support import activate_admin, auth_headers, test_client
from tests.support import settings as test_settings

from app.application.agents.tools.builder import build_unified_agent_tool
from app.application.agents.tools.runtime import UnifiedAgentToolRuntime
from app.domain.agents.approval import model_decides_mcp_approval
from app.domain.agents.runtime import AgentExecutionPaused, run_agent
from app.domain.tools.runtime import build_tool_snapshot
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.tools import repository
from app.infra.db.session import get_session_factory
from app.ports.tools import ToolRuntimeResult


def assert_mcp_conversation_approval():
    discovery = SimpleNamespace(
        tools=[
            {
                "name": "lookup",
                "description": "Look up the user's records.",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
        ]
    )
    with (
        test_client() as client,
        agent_model_server() as model_url,
        patch(
            "app.application.agents.runs.service.enqueue_prepared_agent_run",
            new=AsyncMock(),
        ),
        patch(
            "app.domain.tools.mcp.service.discover_mcp_tools",
            new=AsyncMock(return_value=discovery),
        ),
    ):
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        root = f"/api/v1/workspaces/{workspace_id}"
        created = client.post(
            root + "/tool-sources/mcp",
            headers=headers,
            json={
                "name": "Approval MCP",
                "url": "https://tools.example.com/mcp",
            },
        )
        assert created.status_code == 201, created.text
        source_id = created.json()["id"]
        tools = client.get(root + "/tools", headers=headers).json()
        leaf = next(item for item in tools if item["source"]["id"] == source_id)
        model = client.post(
            root + "/models", headers=headers, json=model_payload(model_url)
        )
        assert model.status_code == 201, model.text
        agent = client.post(
            agents_url(workspace_id),
            headers=headers,
            json={
                "name": "MCP approval",
                "model_id": model.json()["id"],
                "tools": [
                    {"tool_id": leaf["id"], "version_id": leaf["current_version_id"]}
                ],
            },
        )
        assert agent.status_code == 201, agent.text
        prepared = client.post(
            agents_url(workspace_id, f"/{agent.json()['id']}/runs"),
            headers=headers,
            json={"goal": "Look up my records", "approval_mode": "ask_risky"},
        )
        assert prepared.status_code == 201, prepared.text

        async def check():
            async with get_session_factory()() as db:
                frozen = await runs.get_agent_run_by_id(db, prepared.json()["id"])
                assert frozen.application_snapshot["mcp_approval_version"] == 2
                tool = await repository.get_tool(db, workspace_id, leaf["id"])
                source = await repository.get_tool_source(db, workspace_id, source_id)
                version = await repository.get_tool_version(
                    db, workspace_id, tool.current_version_id
                )
                policy = await repository.get_tool_policy(db, workspace_id, tool.id)
                snapshot = build_tool_snapshot(
                    tool, source, version, policy, frozen.execution_user_id
                )

            class Adapter:
                kind = "mcp"
                calls = 0

                async def invoke(self, _snapshot, arguments, _context):
                    assert arguments == {"query": "my records"}
                    self.calls += 1
                    return ToolRuntimeResult(
                        ok=True,
                        data={"records": []},
                        summary="Done",
                        error_code=None,
                        error_message=None,
                        outcome="confirmed",
                        usage={},
                    )

            adapter = Adapter()
            for access in ("console", "public"):
                for mode, decision, requires in (
                    ("always_ask", False, True),
                    ("ask_risky", False, False),
                    ("ask_risky", True, True),
                    ("ask_risky", None, True),
                    ("full_access", True, False),
                ):
                    run = AgentRun(
                        workspace_id=workspace_id,
                        agent_id=agent.json()["id"],
                        requested_by_user_id=(
                            frozen.execution_user_id if access == "console" else None
                        ),
                        consumer_id=frozen.execution_user_id,
                        execution_user_id=frozen.execution_user_id,
                        access_source=access,
                        configuration_source="draft",
                        status="running_v2",
                        worker_task_id="approval-worker",
                        lease_expires_at=utc_now() + timedelta(minutes=5),
                        application_snapshot={
                            "approval_mode": mode,
                            "mcp_approval_version": 2,
                        },
                    )
                    run.root_run_id = run.id
                    async with get_session_factory()() as db:
                        await runs.create_agent_run(db, run)
                        await db.commit()
                    runtime = UnifiedAgentToolRuntime(
                        run,
                        [snapshot],
                        "approval-worker",
                        test_settings(),
                        asyncio.Event(),
                    )
                    exposed = build_unified_agent_tool(
                        snapshot, model_decides_approval=model_decides_mcp_approval(run)
                    )
                    arguments = {"query": "my records"}
                    if model_decides_mcp_approval(run):
                        arguments = {"arguments": arguments}
                        if decision is not None:
                            arguments["requires_approval"] = decision
                    model = ScriptedModel(
                        [
                            AIMessage(
                                content="",
                                tool_calls=[
                                    {
                                        "name": exposed.name,
                                        "args": arguments,
                                        "id": "lookup",
                                        "type": "tool_call",
                                    }
                                ],
                                response_metadata={"finish_reason": "tool_calls"},
                            ),
                            answer_message("Done"),
                        ]
                    )
                    checkpoints = []

                    async def save(state, _phase):
                        checkpoints.append(state)

                    previous_calls = adapter.calls
                    with patch(
                        "app.application.tools.runtime.service.build_tool_adapter",
                        return_value=adapter,
                    ):
                        try:
                            await run_agent(
                                model,
                                [{"role": "user", "content": "Look up my records"}],
                                [exposed],
                                before_tool_call=runtime.before,
                                on_checkpoint=save,
                            )
                        except AgentExecutionPaused:
                            assert requires
                        else:
                            assert not requires
                        async with get_session_factory()() as db:
                            invocations = await repository.list_tool_invocations(
                                db, workspace_id, run.id
                            )
                            assert len(invocations) == 1
                            invocation = invocations[0]
                            assert invocation.arguments == {"query": "my records"}
                            assert (
                                invocation.policy_snapshot["approval_required"]
                                is requires
                            )
                            if requires:
                                assert adapter.calls == previous_calls
                                assert invocation.status == "awaiting_approval"
                                assert (
                                    await repository.resolve_tool_invocation_approval(
                                        db,
                                        workspace_id,
                                        invocation.id,
                                        frozen.execution_user_id,
                                        utc_now(),
                                        utc_now() + timedelta(minutes=1),
                                        approve=True,
                                    )
                                )
                                await db.commit()
                        if requires:
                            await run_agent(
                                model,
                                [],
                                [exposed],
                                checkpoint=checkpoints[-1],
                                before_tool_call=runtime.before,
                            )
                        assert adapter.calls == previous_calls + 1
                        # A replay uses the persisted decision/result and never sends twice.
                        replay = await runtime.before(
                            1,
                            {"id": "lookup", "name": exposed.name, "arguments": "{}"},
                            {"model_requires_approval": "false"},
                            {"query": "my records"},
                        )
                        assert not replay.is_error
                        assert adapter.calls == previous_calls + 1

            # Full access still respects a live source kill switch.
            async with get_session_factory()() as db:
                source.status = "disabled"
                await repository.save_tool_source(db, source)
                await db.commit()
            with patch(
                "app.application.tools.runtime.service.build_tool_adapter",
                return_value=adapter,
            ):
                blocked = await runtime.before(
                    2,
                    {"id": "disabled", "name": exposed.name, "arguments": "{}"},
                    {},
                    {"query": "my records"},
                )
            assert blocked.is_error
            assert "unavailable" in blocked.content.lower()
            assert adapter.calls == 10

        asyncio.run(check())
