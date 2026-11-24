"""Regression checks for queued configurations, recovery, and live authorization."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

import tests.support  # noqa: F401
from tests.automations.api import (
    _seed_model,
    _set_automation_next_run_at,
    _simple_workflow_graph,
)
from tests.support import activate_admin, auth_headers, settings, test_client

from app.application.automations.scheduler import (
    process_due_automations,
    reconcile_automation_notifications,
    recover_pending_automation_executions,
)
from app.application.automations.service import dispatch_execution_by_id
from app.entities.defaults import utc_now


async def assert_automation_tool_execution(run_id, runtime_settings):
    """Exercise the Agent bridge, real ledger, approvals and replay without network I/O."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.application.agents.tools.runtime import (
        UnifiedAgentToolRuntime,
        agent_tool_invocation_identity,
    )
    from app.application.tools.runtime.service import execute_tool_invocation
    from app.domain.agents.runtime import AgentExecutionPaused
    from app.domain.tools.runtime import tool_snapshot_from_payload
    from app.infra.db.repositories.agents import repository as runs
    from app.infra.db.repositories.tools import repository as tools
    from app.infra.db.session import get_session_factory
    from app.ports.tools import ToolRuntimeResult

    worker_id = "automation-tool-worker"
    async with get_session_factory()() as db:
        now = utc_now()
        assert await runs.claim_agent_run(
            db,
            run_id,
            worker_id,
            now,
            now + timedelta(seconds=60),
            generation="unified",
        )
        await db.commit()
        run = await runs.get_agent_run_by_id(db, run_id)
    snapshots = [tool_snapshot_from_payload(item) for item in run.tool_snapshots]
    runtime = UnifiedAgentToolRuntime(
        run, snapshots, worker_id, runtime_settings, asyncio.Event()
    )
    adapter_call = AsyncMock(
        return_value=ToolRuntimeResult(
            ok=True,
            data={"text": "fixture result"},
            summary="Fixture result",
            error_code=None,
            error_message=None,
            outcome="confirmed",
            usage={},
        )
    )
    with patch(
        "app.application.tools.runtime.service.build_tool_adapter",
        side_effect=lambda snapshot, *_: SimpleNamespace(
            kind=snapshot.kind, invoke=adapter_call
        ),
    ):
        for index, (name, arguments) in enumerate(
            [
                ("bash", {"command": "printf OK"}),
                ("automation_mcp_probe", {}),
            ],
            start=1,
        ):
            call = {"id": name, "name": name, "arguments": arguments}
            if name == "automation_mcp_probe":
                try:
                    await runtime.before(index, call, {}, arguments)
                except AgentExecutionPaused:
                    pass
                else:
                    raise AssertionError("Automation MCP call bypassed approval.")
                _, key = agent_tool_invocation_identity(run.id, index, name)
                async with get_session_factory()() as db:
                    invocation = await tools.get_tool_invocation_by_idempotency_key(
                        db, run.workspace_id, key
                    )
                    assert invocation.status == "awaiting_approval"
                    assert adapter_call.await_count == 1  # Only bash has executed.
                    assert await tools.resolve_tool_invocation_approval(
                        db,
                        run.workspace_id,
                        invocation.id,
                        run.consumer_id,
                        utc_now(),
                        utc_now() + timedelta(seconds=30),
                        approve=True,
                    )
                    await db.commit()
            result = await runtime.before(index, call, {}, arguments)
            assert not result.is_error, result.content
            _, key = agent_tool_invocation_identity(run.id, index, name)
            async with get_session_factory()() as db:
                invocation = await tools.get_tool_invocation_by_idempotency_key(
                    db, run.workspace_id, key
                )
                assert invocation.status == "succeeded"
                assert invocation.access_source == "automation"
                assert invocation.execution_user_id == run.execution_user_id
                assert (
                    invocation.run_id == run.id
                    and invocation.root_run_id == run.root_run_id
                )
            # Worker replay returns the durable result without dispatching twice.
            calls_before = adapter_call.await_count
            replay = await execute_tool_invocation(
                invocation.id, runtime_settings, "replay-worker"
            )
            assert replay.ok and adapter_call.await_count == calls_before
        assert adapter_call.await_count == 2
    # Leave the lease expired so the existing revoked-publication test can reclaim.
    async with get_session_factory()() as db:
        current = await runs.get_agent_run_by_id(db, run.id)
        current.lease_expires_at = utc_now() - timedelta(seconds=1)
        await runs.save_agent_run(db, current)
        await db.commit()


def assert_workflow_form_resume(
    client, headers, base, model_id, runtime_settings, *, tool_ref=None
):
    """Exercise the real worker and preserve its first deadline across a form wait."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    from app.application.workflows.runs.executor import run_durable_workflow_run
    from app.domain.workflows.models import WorkflowRunDetail
    from app.infra.db.session import get_session_factory
    from app.ports.tools import ToolRuntimeResult

    response = client.post(
        f"{base}/agents",
        headers=headers,
        json={
            "name": "Worker smoke",
            "app_type": "workflow",
            "model_id": model_id,
            "instructions": "Use the confirmation form",
        },
    )
    response.raise_for_status()
    workflow_id = response.json()["id"]
    workflow_url = f"{base}/workflows/{workflow_id}"
    graph = _simple_workflow_graph()
    if tool_ref:
        graph["nodes"].append(
            {
                "id": "mcp-probe",
                "type": "workflow",
                "position": {"x": 300, "y": 0},
                "data": {
                    "title": "MCP probe",
                    "type": "tool",
                    "config": {"tool": tool_ref},
                },
            }
        )
        graph["edges"][1]["target"] = "mcp-probe"
        graph["edges"].append(
            {
                "id": "e3",
                "source": "mcp-probe",
                "target": "answer-1",
                "sourceHandle": None,
                "targetHandle": None,
            }
        )
    client.put(
        f"{workflow_url}/definition",
        headers=headers,
        json={"graph": graph, "expected_revision": 1},
    ).raise_for_status()
    client.post(f"{workflow_url}/publish", headers=headers).raise_for_status()
    response = client.post(
        f"{base}/automations",
        headers=headers,
        json={
            "name": "Worker smoke",
            "target_app_id": workflow_id,
            "trigger_type": "daily",
            "trigger_config": {"hour": 9, "minute": 0},
            "input_config": {"mode": "text", "text": "Confirm the environment"},
            "approval_mode": "full_access" if tool_ref else "always_ask",
        },
    )
    response.raise_for_status()
    worker_url = f"{base}/automations/{response.json()['id']}"
    invoke = AsyncMock(
        return_value=ToolRuntimeResult(
            ok=True,
            data={"text": "fixture result"},
            summary="Fixture result",
            error_code=None,
            error_message=None,
            outcome="confirmed",
            usage={},
        )
    )
    with (
        patch("app.application.automations.service.enqueue_prepared_agent_run"),
        patch("app.application.workflows.runs.service.enqueue_agent_run"),
        patch(
            "app.application.tools.runtime.service.build_tool_adapter",
            return_value=SimpleNamespace(kind="mcp", invoke=invoke),
        ),
    ):
        response = client.post(f"{worker_url}/execute", headers=headers)
        response.raise_for_status()
        execution = response.json()
        asyncio.run(
            run_durable_workflow_run(
                execution["run_id"], runtime_settings, generation="unified"
            )
        )
        detail_url = f"{worker_url}/executions/{execution['id']}"
        waiting = client.get(detail_url, headers=headers).json()
        assert waiting["run_status"] == "awaiting_input", waiting

        async def deadline():
            async with get_session_factory()() as db:
                detail = await db.scalar(
                    select(WorkflowRunDetail).where(
                        WorkflowRunDetail.run_id == execution["run_id"]
                    )
                )
                return detail.deadline_at

        original_deadline = asyncio.run(deadline())
        client.post(
            f"{detail_url}/form",
            headers=headers,
            json={"runtime_node_id": "form-1", "form_data": {"env": "production"}},
        ).raise_for_status()
        asyncio.run(
            run_durable_workflow_run(
                execution["run_id"], runtime_settings, generation="unified"
            )
        )
        completed = client.get(detail_url, headers=headers).json()
        assert completed["run_status"] == "succeeded", completed
        assert completed["workflow_run"]["outputs"]["result"] == "production"
        assert asyncio.run(deadline()) == original_deadline
        assert invoke.await_count == int(tool_ref is not None)
        if tool_ref:
            context = invoke.await_args.args[2]
            assert (
                context.origin == "workflow" and context.access_source == "automation"
            )
            assert context.run_id == execution["run_id"]


def test_frozen_config_and_recovery() -> None:
    runtime_settings = settings()
    with test_client() as client:
        token, workspace_id = activate_admin(client)
        headers = auth_headers(token)
        base = f"/api/v1/workspaces/{workspace_id}"
        model_id = _seed_model(client, token, workspace_id)
        from tests.tools.tools import seed_private_tool

        from app.entities.tools import ToolPolicy
        from app.infra.db.repositories.tools import repository as tools
        from app.infra.db.session import get_session_factory

        owner_id = client.get("/api/v1/auth/me", headers=headers).json()["user"]["id"]
        mcp_tool, mcp_version = asyncio.run(
            seed_private_tool(workspace_id, owner_id, "automation_mcp_probe")
        )

        async def allow_mcp_tool():
            async with get_session_factory()() as db:
                await tools.save_tool_policy(
                    db,
                    ToolPolicy(
                        workspace_id=workspace_id,
                        tool_id=mcp_tool.id,
                        tool_version_id=mcp_version.id,
                        definition_hash=mcp_version.definition_hash,
                        approval="each_call",
                        effect="external_read",
                        allowed_access_sources=["console"],
                        workflow_callable=True,
                        reviewed_by_user_id=owner_id,
                    ),
                )
                await db.commit()

        asyncio.run(allow_mcp_tool())
        agent = client.post(
            f"{base}/agents",
            headers=headers,
            json={
                "name": "Frozen worker",
                "instructions": "Version one",
                "model_id": model_id,
                "tools": [{"tool_id": mcp_tool.id, "version_id": mcp_version.id}],
            },
        ).json()
        app_url = f"{base}/agents/{agent['id']}"
        client.patch(
            app_url, headers=headers, json={"published": True}
        ).raise_for_status()
        v1 = client.get(f"{app_url}/versions", headers=headers).json()["items"][0]["id"]
        client.patch(
            app_url,
            headers=headers,
            json={"published": True, "instructions": "Version two"},
        ).raise_for_status()
        v2 = client.get(f"{app_url}/versions", headers=headers).json()["items"][0]["id"]
        payload = {
            "name": "Frozen schedule",
            "target_app_id": agent["id"],
            "publication_version_id": v1,
            "approval_mode": "always_ask",
            "trigger_type": "daily",
            "trigger_config": {"hour": 9, "minute": 0},
            "input_config": {"mode": "text", "text": "Original input"},
        }
        created = client.post(f"{base}/automations", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        auto_url = f"{base}/automations/{created.json()['id']}"
        with patch(
            "app.application.automations.service.dispatch_execution_by_id",
            return_value=None,
        ):
            queued = client.post(
                f"{auto_url}/execute", headers=headers, json={"request_id": "frozen"}
            )
        assert queued.status_code == 202, queued.text
        execution_id = queued.json()["id"]
        overdue = utc_now() - timedelta(days=2)
        asyncio.run(_set_automation_next_run_at(created.json()["id"], overdue))
        updated = client.patch(
            auto_url,
            headers=headers,
            json={
                "publication_version_id": v2,
                "approval_mode": "full_access",
                "input_config": {"mode": "text", "text": "Changed input"},
            },
        )
        assert updated.status_code == 200, updated.text
        enqueued = []

        async def enqueue(run_id, *_args, **_kwargs):
            enqueued.append(run_id)

        with patch(
            "app.application.automations.service.enqueue_prepared_agent_run",
            side_effect=enqueue,
        ):
            asyncio.run(dispatch_execution_by_id(execution_id, runtime_settings))
        detail = client.get(
            f"{auto_url}/executions/{execution_id}", headers=headers
        ).json()
        assert detail["agent_run"]["goal"] == "Original input"
        assert detail["agent_run"]["approval_mode"] == "always_ask", detail
        assert detail["frozen_config"]["publication_version_id"] == v1

        async def check_pinned_run():
            from app.infra.db.repositories.agents import repository
            from app.infra.db.session import get_session_factory

            async with get_session_factory()() as db:
                run = await repository.get_agent_run_by_id(db, detail["run_id"])
                assert run.agent_publication_version_id == v1

        asyncio.run(check_pinned_run())
        asyncio.run(
            assert_automation_tool_execution(detail["run_id"], runtime_settings)
        )
        # Editing inputs or a name must not discard an overdue, unprocessed schedule slot.
        assert datetime.fromisoformat(updated.json()["next_run_at"]) == overdue

        # A pending queue publish must stay paused, then recover without creating a second Run.
        pending_auto = client.post(
            f"{base}/automations",
            headers=headers,
            json={**payload, "name": "Pending publish"},
        ).json()
        pending_url = f"{base}/automations/{pending_auto['id']}"
        with patch(
            "app.application.automations.service.enqueue_prepared_agent_run",
            side_effect=RuntimeError("offline"),
        ):
            pending = client.post(f"{pending_url}/execute", headers=headers).json()
        assert pending["dispatch_status"] == "pending_dispatch"
        client.post(f"{pending_url}/pause", headers=headers).raise_for_status()
        with patch(
            "app.application.automations.service.enqueue_prepared_agent_run",
            side_effect=enqueue,
        ):
            before = len(enqueued)
            asyncio.run(recover_pending_automation_executions(runtime_settings))
            assert len(enqueued) == before
            client.post(f"{pending_url}/resume", headers=headers).raise_for_status()
            asyncio.run(recover_pending_automation_executions(runtime_settings))
        recovered = client.get(
            f"{pending_url}/executions/{pending['id']}", headers=headers
        ).json()
        assert recovered["run_id"] == pending["run_id"]
        assert recovered["dispatch_status"] == "dispatched"

        # A one-time trigger paused over its due time must still run once on resume.
        one_time = client.post(
            f"{base}/automations",
            headers=headers,
            json={
                **payload,
                "name": "Paused once",
                "trigger_type": "once",
                "trigger_config": {
                    "run_at": (utc_now() - timedelta(minutes=1)).isoformat()
                },
            },
        ).json()
        once_url = f"{base}/automations/{one_time['id']}"
        client.post(f"{once_url}/pause", headers=headers).raise_for_status()
        resumed = client.post(f"{once_url}/resume", headers=headers)
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["next_run_at"] is not None
        with patch(
            "app.application.automations.service.enqueue_prepared_agent_run",
            side_effect=enqueue,
        ):
            asyncio.run(process_due_automations(runtime_settings))
            asyncio.run(process_due_automations(runtime_settings))
        history = client.get(f"{once_url}/executions", headers=headers).json()
        assert history["total"] == 1

        client.post(
            f"{once_url}/executions/" + history["items"][0]["id"] + "/cancel",
            headers=headers,
        ).raise_for_status()

        # Queued cancellation also has a durable notification, without creating a Run.
        queued_auto = client.post(
            f"{base}/automations",
            headers=headers,
            json={**payload, "name": "Cancel queued"},
        ).json()
        queued_url = f"{base}/automations/{queued_auto['id']}"
        with patch(
            "app.application.automations.service.dispatch_execution_by_id",
            return_value=None,
        ):
            queued = client.post(f"{queued_url}/execute", headers=headers).json()
        cancelled = client.post(
            f"{queued_url}/executions/{queued['id']}/cancel", headers=headers
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["run_status"] == "cancelled"

        # Rejection before a Run exists still produces one failure notification.
        client.patch(
            app_url, headers=headers, json={"published": False}
        ).raise_for_status()
        from app.application.agents.runs.executor import run_durable_unified_agent_run

        with patch(
            "app.application.agents.runs.executor.build_chat_model"
        ) as model_factory:
            asyncio.run(
                run_durable_unified_agent_run(detail["run_id"], runtime_settings)
            )
            model_factory.assert_not_called()
        rejected = client.post(f"{once_url}/execute", headers=headers).json()
        assert rejected["dispatch_status"] == "rejected"
        with patch(
            "app.application.automations.scheduler.publish_live_task_notification"
        ):
            asyncio.run(reconcile_automation_notifications(runtime_settings))
            asyncio.run(reconcile_automation_notifications(runtime_settings))
        messages = client.get(
            f"/api/v1/messages?workspace_id={workspace_id}", headers=headers
        ).json()
        assert (
            len([m for m in messages if m.get("execution_id") == rejected["id"]]) == 1
        )
        assert (
            len(
                [
                    m
                    for m in messages
                    if m.get("execution_id") == queued["id"]
                    and m.get("event_type") == "cancelled"
                ]
            )
            == 1
        )
        assert_workflow_form_resume(
            client,
            headers,
            base,
            model_id,
            runtime_settings,
            tool_ref={"tool_id": mcp_tool.id, "version_id": mcp_version.id},
        )


if __name__ == "__main__":
    test_frozen_config_and_recovery()
    print("AUTOMATIONS_RELIABILITY_OK")
