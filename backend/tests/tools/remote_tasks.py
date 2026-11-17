"""Real HTTP MCP lifecycle, persisted recovery, cancellation and policy fencing."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from tests import support
from tests.infra.mcp_transports import TOKEN, start_http_server, stop_process
from tests.support import activate_admin, auth_headers, create_active_user, test_client

from app.application.agents.tools.runtime import UnifiedAgentToolRuntime
from app.application.tools.remote_task_cleanup import recover_remote_task_cancellations
from app.application.tools.runtime.contracts import ToolInvocationContext
from app.application.tools.runtime.service import (
    execute_tool_invocation,
    queue_tool_invocation,
)
from app.domain.tools.mcp.task_contract import apply_task_contracts, server_binding
from app.domain.tools.runtime import build_tool_snapshot
from app.entities.defaults import utc_now
from app.entities.mcp_tasks import McpRemoteTask
from app.entities.runs import AgentRun
from app.infra.db.repositories.identity import users
from app.infra.db.repositories.tools import mcp as mcp_repository
from app.infra.db.repositories.tools import remote_tasks as tasks
from app.infra.db.repositories.tools import repository
from app.infra.db.session import get_session_factory
from app.ports.mcp import McpConnection, call_mcp_tool


async def queue(workspace_id, message, timeout=20):
    async with get_session_factory()() as db:
        actor = await users.get_active_user_by_username(db, "admin")
        tool = next(
            item
            for item in await repository.list_tools(db, workspace_id)
            if item.stable_key == "job_submit"
        )
        source = await repository.get_tool_source(db, workspace_id, tool.source_id)
        version = await repository.get_tool_version(
            db, workspace_id, tool.current_version_id
        )
        policy = await repository.get_tool_policy(db, workspace_id, tool.id)
        snapshot = build_tool_snapshot(tool, source, version, policy, actor.id)
        assert snapshot.execution_spec["long_task"]["status_tool"] == "job_status"
        run = AgentRun(
            workspace_id=workspace_id,
            execution_user_id=actor.id,
            execution_deadline_at=utc_now() + timedelta(seconds=600),
        )
        runtime = UnifiedAgentToolRuntime(
            run, [snapshot], "deadline-test", support.settings(), asyncio.Event()
        )
        assert runtime._tool_deadline(snapshot) == run.execution_deadline_at
        ordinary = replace(snapshot, execution_spec={"tool_name": "ordinary"})
        assert runtime._tool_deadline(ordinary) < run.execution_deadline_at
        key = "remote-task-" + uuid4().hex
        context = ToolInvocationContext(
            workspace_id=workspace_id,
            origin="test",
            root_run_id=None,
            run_id=None,
            invocation_id=key,
            execution_user_id=actor.id,
            access_source="console",
            deadline_at=utc_now() + timedelta(seconds=timeout),
            idempotency_key=key,
        )
        invocation = await queue_tool_invocation(
            db, snapshot, {"message": message}, context
        )
        await repository.resolve_tool_invocation_approval(
            db,
            workspace_id,
            invocation.id,
            actor.id,
            utc_now(),
            context.deadline_at,
            approve=True,
        )
        await db.commit()
        return invocation.id, snapshot, context


async def resume_fixture(
    invocation_id, snapshot, context, connection, settings, *, lose_identity=False
):
    # Simulate the durable state at a process crash, using an actual remote job.
    async with get_session_factory()() as db:
        claimed = await repository.claim_tool_invocation(
            db,
            context.workspace_id,
            invocation_id,
            "dead-worker",
            utc_now(),
            utc_now() + timedelta(seconds=30),
        )
        assert claimed
        await db.commit()
    receipt = await call_mcp_tool(
        connection,
        settings,
        "job_submit",
        {"message": "recovered"},
        idempotency_key=context.idempotency_key,
    )
    async with get_session_factory()() as db:
        server = await mcp_repository.get_mcp_server_by_id(
            db, snapshot.execution_spec["server_id"]
        )
        await tasks.save(
            db,
            McpRemoteTask(
                invocation_id=invocation_id,
                workspace_id=context.workspace_id,
                server_id=server.id,
                server_binding=server_binding(server),
                request_key=context.idempotency_key,
                contract=dict(snapshot.execution_spec["long_task"]),
                remote_id=None
                if lose_identity
                else receipt.structured_content["task_id"],
                status="submitting" if lose_identity else "running",
                deadline_at=context.deadline_at,
            ),
        )
        invocation = await repository.get_tool_invocation_by_id(db, invocation_id)
        invocation.lease_expires_at = utc_now() - timedelta(seconds=1)
        invocation.attempts = invocation.max_attempts
        await repository.save_tool_invocation(db, invocation)
        await db.commit()
    result = await execute_tool_invocation(invocation_id, settings, "recovery-worker")
    assert result.ok and result.data["structuredContent"]["result"] == "recovered", (
        result
    )
    async with get_session_factory()() as db:
        stored = await repository.get_tool_invocation_by_id(db, invocation_id)
        assert stored.attempts == stored.max_attempts and stored.status == "succeeded"


def main():
    process, url = start_http_server("streamable-http", long_tasks=True)
    settings = replace(
        support.settings(),
        mcp_allow_private_networks=True,
        mcp_request_timeout_seconds=3,
    )
    connection = McpConnection(
        transport="streamable_http",
        url=url,
        bearer_token=TOKEN,
        network_policy="deployment",
    )
    try:
        with (
            patch.object(support, "settings", return_value=settings),
            test_client() as client,
        ):
            token, workspace_id = activate_admin(client)
            headers = auth_headers(token)
            root = f"/api/v1/workspaces/{workspace_id}"
            created = client.post(
                root + "/mcp-servers",
                headers=headers,
                json={"name": "Durable jobs", "url": url, "bearer_token": TOKEN},
            )
            assert created.status_code == 201, created.text
            base = root + f"/mcp-servers/{created.json()['id']}"
            contract = {
                "status_tool": "job_status",
                "result_tool": "job_result",
                "cancel_tool": "job_cancel",
                "poll_seconds": 1,
            }
            configured = client.put(
                base + "/long-tasks",
                headers=headers,
                json={"contracts": {"job_submit": contract}},
            )
            assert configured.status_code == 200, configured.text
            assert configured.json()["contracts"]["job_submit"] == contract
            tools = client.get(root + "/tools", headers=headers).json()
            tool = next(item for item in tools if item["display_name"] == "job_submit")
            reviewed = client.put(
                root + f"/tools/{tool['id']}/policy",
                headers=headers,
                json={"mode": "approval_required"},
            )
            assert reviewed.status_code == 200, reviewed.text
            invocation_id, snapshot, context = client.portal.call(
                queue, workspace_id, "completed"
            )
            result = client.portal.call(
                execute_tool_invocation, invocation_id, settings, "first-worker"
            )
            assert (
                result.ok and result.data["structuredContent"]["result"] == "completed"
            ), result
            assert result.data["_meta"]["nexaflow/remoteTask"]["status"] == "succeeded"
            client.portal.call(
                execute_tool_invocation, invocation_id, settings, "replayed-worker"
            )
            for lose_identity in (False, True):
                ident, frozen, current = client.portal.call(
                    queue, workspace_id, "recovered"
                )

                async def recover():
                    await resume_fixture(
                        ident,
                        frozen,
                        current,
                        connection,
                        settings,
                        lose_identity=lose_identity,
                    )

                client.portal.call(recover)
            metrics = client.portal.call(
                call_mcp_tool, connection, settings, "job_metrics", {}
            )
            assert (
                metrics.structured_content["submits"] == 3
                and metrics.structured_content["jobs"] == 3
            ), metrics

            ident, _frozen, _current = client.portal.call(
                queue, workspace_id, "forever", 1
            )
            timed_out = client.portal.call(
                execute_tool_invocation, ident, settings, "timeout-worker"
            )
            assert not timed_out.ok and timed_out.outcome == "uncertain", timed_out

            async def assert_cancel():
                async with get_session_factory()() as db:
                    task = await tasks.get(db, ident)
                    assert task.cancel_requested and task.remote_id
                await recover_remote_task_cancellations(settings)
                async with get_session_factory()() as db:
                    assert (await tasks.get(db, ident)).status == "cancelled"
                await recover_remote_task_cancellations(settings)

            client.portal.call(assert_cancel)
            metrics = client.portal.call(
                call_mcp_tool, connection, settings, "job_metrics", {}
            )
            assert metrics.structured_content["cancels"] == 1

            ident, _frozen, _current = client.portal.call(
                queue, workspace_id, "must not submit"
            )
            # Changing the lifecycle definition invalidates old approvals/snapshots.
            assert (
                client.put(
                    base + "/long-tasks",
                    headers=headers,
                    json={"contracts": {"job_submit": contract | {"poll_seconds": 2}}},
                ).status_code
                == 200
            )
            changed = client.portal.call(
                execute_tool_invocation, ident, settings, "stale-definition-worker"
            )
            assert not changed.ok and changed.error_code == "tool_definition_changed", (
                changed
            )
            assert (
                client.put(
                    base + "/long-tasks",
                    headers=headers,
                    json={
                        "contracts": {
                            "job_submit": contract | {"status_tool": "job_submit"}
                        }
                    },
                ).status_code
                == 422
            )
            other_id, other_token = create_active_user(client, token, "tasks-other")
            assert (
                client.post(
                    root + "/members",
                    headers=headers,
                    json={"user_id": other_id, "role": "admin"},
                ).status_code
                == 201
            )
            assert (
                client.get(
                    base + "/long-tasks", headers=auth_headers(other_token)
                ).status_code
                == 404
            )
            stripped = apply_task_contracts(
                [
                    {
                        "name": "untrusted",
                        "long_task": contract,
                        "annotations": {"nexaflowLongTask": contract},
                    }
                ],
                {},
            )
            assert "long_task" not in stripped[0] and not stripped[0]["annotations"]
            unavailable = apply_task_contracts(
                [
                    {"name": "job_submit"},
                    {"name": "job_status"},
                    {"name": "job_result"},
                ],
                {"job_submit": contract},
            )
            assert "job_submit" not in {item["name"] for item in unavailable}
    finally:
        stop_process(process)
    print("MCP_REMOTE_TASKS_OK")


if __name__ == "__main__":
    main()
