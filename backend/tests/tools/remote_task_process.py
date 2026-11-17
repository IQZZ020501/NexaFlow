"""SIGKILL a real worker, then recover its PostgreSQL job without resubmitting.

Requires NEXAFLOW_TEST_DATABASE_URL pointing to an explicitly isolated,
fully migrated PostgreSQL database. Never points at local product data.
"""

import os
import subprocess
import sys
import time
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete
from tests.infra.mcp_transports import TOKEN, start_http_server, stop_process
from tests.support import ADMIN_PASSWORD, activate_user, auth_headers, settings
from tests.tools.remote_tasks import queue

from app.application.tools.runtime.service import execute_tool_invocation
from app.domain.tools.mcp.task_models import McpRemoteTask
from app.entities.defaults import utc_now
from app.infra.db.repositories.tools import remote_tasks as tasks
from app.infra.db.repositories.tools import repository
from app.infra.db.session import configure_database, get_session_factory
from app.main import create_app
from app.ports.mcp import McpConnection, call_mcp_tool


def main():
    database = os.environ["NEXAFLOW_TEST_DATABASE_URL"]
    assert database.startswith("postgresql+psycopg://")
    label = "task-process-" + uuid4().hex[:12]
    runtime = replace(
        settings(),
        database_url=database,
        mcp_allow_private_networks=True,
        mcp_request_timeout_seconds=3,
        bootstrap_admin_username=label,
        bootstrap_admin_email=label + "@example.com",
    )
    provider, url = start_http_server("streamable-http", long_tasks=True)
    worker = None
    workspace_id = None
    try:
        app = create_app(runtime)
        configure_database(runtime, worker_process=True)
        with TestClient(app) as client:
            token = activate_user(
                client, label, runtime.bootstrap_admin_password, ADMIN_PASSWORD
            )
            headers = auth_headers(token)
            actor_id = client.get("/api/v1/auth/me", headers=headers).json()["user"][
                "id"
            ]
            created = client.post(
                "/api/v1/workspaces",
                headers=headers,
                json={"name": label, "admin_user_id": actor_id},
            )
            assert created.status_code == 201, created.text
            workspace_id = created.json()["workspace"]["id"]
            root = f"/api/v1/workspaces/{workspace_id}"
            created = client.post(
                root + "/mcp-servers",
                headers=headers,
                json={"name": label, "url": url, "bearer_token": TOKEN},
            )
            assert created.status_code == 201, created.text
            server_id = created.json()["id"]
            contract = {
                "status_tool": "job_status",
                "result_tool": "job_result",
                "cancel_tool": "job_cancel",
                "poll_seconds": 30,
            }
            configured = client.put(
                root + f"/mcp-servers/{server_id}/long-tasks",
                headers=headers,
                json={"contracts": {"job_submit": contract}},
            )
            assert configured.status_code == 200, configured.text
            tool = next(
                item
                for item in client.get(root + "/tools", headers=headers).json()
                if item["display_name"] == "job_submit"
            )
            assert (
                client.put(
                    root + f"/tools/{tool['id']}/policy",
                    headers=headers,
                    json={"mode": "approval_required"},
                ).status_code
                == 200
            )
            # queue() normally selects the bootstrap fixture username.
            from unittest.mock import patch

            from app.infra.db.repositories.identity import users

            original = users.get_active_user_by_username

            async def actor(db, _username):
                return await original(db, label)

            with patch.object(users, "get_active_user_by_username", new=actor):
                invocation_id, _snapshot, context = client.portal.call(
                    queue, workspace_id, "process recovery", 90
                )
            worker = subprocess.Popen(
                [sys.executable, "-m", "tests.tools.remote_task_worker", invocation_id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            async def saved_task():
                async with get_session_factory()() as db:
                    return await tasks.get(db, invocation_id)

            task = None
            for _ in range(300):
                if worker.poll() is not None:
                    raise AssertionError(
                        "Worker exited before the persisted crash point"
                    )
                task = client.portal.call(saved_task)
                if task and task.remote_id:
                    break
                time.sleep(0.03)
            assert task and task.remote_id
            worker.kill()
            worker.wait(timeout=5)
            assert worker.returncode < 0
            connection = McpConnection(
                transport="streamable_http",
                url=url,
                bearer_token=TOKEN,
                network_policy="deployment",
            )
            # Let the remote fixture finish while the original worker is gone.
            for _ in range(2):
                client.portal.call(
                    call_mcp_tool,
                    connection,
                    runtime,
                    "job_status",
                    {"request_id": context.idempotency_key, "task_id": task.remote_id},
                )

            async def expire():
                async with get_session_factory()() as db:
                    invocation = await repository.get_tool_invocation_by_id(
                        db, invocation_id
                    )
                    invocation.lease_expires_at = utc_now() - timedelta(seconds=1)
                    await repository.save_tool_invocation(db, invocation)
                    await db.commit()

            client.portal.call(expire)
            result = client.portal.call(
                execute_tool_invocation, invocation_id, runtime, "replacement-worker"
            )
            assert (
                result.ok
                and result.data["structuredContent"]["result"] == "process recovery"
            ), result
            metrics = client.portal.call(
                call_mcp_tool, connection, runtime, "job_metrics", {}
            )
            assert (
                metrics.structured_content["submits"] == 1
                and metrics.structured_content["jobs"] == 1
            ), metrics
            assert client.delete(root, headers=headers).status_code == 204

            async def cleanup():
                async with get_session_factory()() as db:
                    await db.execute(
                        delete(McpRemoteTask).where(
                            McpRemoteTask.workspace_id == workspace_id
                        )
                    )
                    await db.commit()

            client.portal.call(cleanup)
    finally:
        if worker and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)
        stop_process(provider)
    print("MCP_REMOTE_TASK_PROCESS_RECOVERY_OK")


if __name__ == "__main__":
    main()
