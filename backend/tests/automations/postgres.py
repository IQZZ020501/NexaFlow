"""Explicit isolated PostgreSQL checks for concurrent triggers and inbox persistence."""

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import tests.support as support
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.automations.api import _seed_model, _set_automation_next_run_at
from tests.automations.reliability import assert_workflow_form_resume

from app.application.automations.scheduler import (
    process_due_automations,
    reconcile_automation_notifications,
)
from app.application.automations.service import dispatch_execution_by_id
from app.domain.agents.models import AgentRun, AgentRunState
from app.domain.automations import sign_webhook_payload
from app.domain.automations.models import AutomationExecution
from app.domain.notifications.models import UserNotification
from app.entities.defaults import utc_now
from app.entities.notifications import UserNotification as NotificationEntity
from app.infra.db.repositories.notifications.repository import (
    create_notification_idempotent,
)
from app.infra.db.session import configure_database, get_session_factory
from app.main import create_app


def check() -> None:
    database = os.environ.get("NEXAFLOW_TEST_DATABASE_URL", "")
    if not database.startswith("postgresql+psycopg://"):
        raise RuntimeError(
            "Set NEXAFLOW_TEST_DATABASE_URL to a migrated, isolated PostgreSQL database."
        )
    config = replace(support.settings(), database_url=database)
    app = create_app(config)
    # Each concurrency scenario uses its own event loop and independent connections.
    configure_database(config, worker_process=True)
    enqueued = []

    async def enqueue(run_id, *_args, **_kwargs):
        enqueued.append(run_id)

    with (
        TestClient(app) as client,
        patch(
            "app.application.automations.service.enqueue_prepared_agent_run",
            side_effect=enqueue,
        ),
        patch("app.application.automations.service._publish_webhook_dispatch"),
        patch(
            "app.application.workflows.runs.service.enqueue_agent_run",
            side_effect=enqueue,
        ),
        patch(
            "app.application.automations.scheduler.publish_live_task_notification",
        ),
    ):
        token, workspace_id = support.activate_admin(client)
        headers = support.auth_headers(token)
        owner_id = client.get("/api/v1/auth/me", headers=headers).json()["user"]["id"]
        base = f"/api/v1/workspaces/{workspace_id}"
        model_id = _seed_model(client, token, workspace_id)
        agent_response = client.post(
            f"{base}/agents",
            headers=headers,
            json={
                "name": "Concurrent automation",
                "instructions": "Return OK",
                "model_id": model_id,
            },
        )
        agent_response.raise_for_status()
        agent_id = agent_response.json()["id"]
        client.patch(
            f"{base}/agents/{agent_id}", headers=headers, json={"published": True}
        ).raise_for_status()
        payload = {
            "name": "Concurrent schedule",
            "target_app_id": agent_id,
            "trigger_type": "daily",
            "trigger_config": {"hour": 9, "minute": 0},
            "input_config": {"mode": "text", "text": "Do the task"},
        }
        automation = client.post(
            f"{base}/automations", headers=headers, json=payload
        ).json()
        now = utc_now()
        asyncio.run(
            _set_automation_next_run_at(automation["id"], now - timedelta(days=2))
        )

        async def concurrent_ticks():
            await asyncio.gather(
                *(process_due_automations(config, now=now) for _ in range(4))
            )
            async with get_session_factory()() as db:
                executions = list(
                    await db.scalars(
                        select(AutomationExecution).where(
                            AutomationExecution.automation_id == automation["id"],
                        )
                    )
                )
                assert len(executions) == 1
                assert executions[0].run_id is not None
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AgentRun)
                        .where(
                            AgentRun.id == executions[0].run_id,
                        )
                    )
                    == 1
                )

        asyncio.run(concurrent_ticks())

        hook = client.post(
            f"{base}/automations",
            headers=headers,
            json={
                **payload,
                "name": "Concurrent hook",
                "trigger_type": "webhook",
                "trigger_config": {},
            },
        ).json()
        raw = json.dumps({"message": "Event"}).encode()
        timestamp = str(int(utc_now().timestamp()))
        event_headers = {
            "Content-Type": "application/json",
            "X-NexaFlow-Timestamp": timestamp,
            "X-NexaFlow-Event-Id": "same-event",
            "X-NexaFlow-Signature": sign_webhook_payload(
                hook["webhook_secret"], timestamp, raw, "same-event"
            ),
        }

        def send(_):
            response = client.post(
                hook["webhook_url"], content=raw, headers=event_headers
            )
            assert response.status_code == 202, response.text
            return response.json()["execution_id"]

        with ThreadPoolExecutor(max_workers=4) as pool:
            receipt_ids = list(pool.map(send, range(8)))
        assert len(set(receipt_ids)) == 1
        # Changing an event ID without signing again cannot replay a captured message.
        assert (
            client.post(
                hook["webhook_url"],
                content=raw,
                headers={
                    **event_headers,
                    "X-NexaFlow-Event-Id": "another-event",
                },
            ).status_code
            == 401
        )
        next_headers = {
            **event_headers,
            "X-NexaFlow-Event-Id": "second-event",
            "X-NexaFlow-Signature": sign_webhook_payload(
                hook["webhook_secret"], timestamp, raw, "second-event"
            ),
        }
        second = client.post(
            hook["webhook_url"], content=raw, headers=next_headers
        ).json()["execution_id"]

        async def concurrent_dispatch():
            # A newer delivery cannot jump over the oldest accepted receipt.
            result = await dispatch_execution_by_id(second, config)
            assert result.run_id is None
            await asyncio.wait_for(
                asyncio.gather(
                    dispatch_execution_by_id(second, config),
                    dispatch_execution_by_id(receipt_ids[0], config),
                    dispatch_execution_by_id(receipt_ids[0], config),
                ),
                timeout=10,
            )
            async with get_session_factory()() as db:
                rows = list(
                    await db.scalars(
                        select(AutomationExecution).where(
                            AutomationExecution.automation_id == hook["id"],
                        )
                    )
                )
                assert sum(row.run_id is not None for row in rows) == 1
                first = next(row for row in rows if row.id == receipt_ids[0])
                state = await db.get(AgentRunState, first.run_id)
                state.status = "awaiting_approval_v2"
                await db.commit()
            # Real PostgreSQL persists a wait marker and its unique notification.
            await reconcile_automation_notifications(config)
            await reconcile_automation_notifications(config)
            async with get_session_factory()() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(UserNotification)
                        .where(
                            UserNotification.execution_id == receipt_ids[0],
                        )
                    )
                    == 1
                )
                for index in range(240):
                    await create_notification_idempotent(
                        db,
                        NotificationEntity(
                            user_id=owner_id,
                            workspace_id=workspace_id,
                            event_type="succeeded",
                            title="Page test",
                            dedup_key=f"page:{index}",
                        ),
                    )
                await db.commit()

        asyncio.run(concurrent_dispatch())
        page = client.get(
            f"/api/v1/messages?workspace_id={workspace_id}&limit=20&offset=200",
            headers=headers,
        )
        assert page.status_code == 200, page.text
        assert len(page.json()) == 20
        assert int(page.headers["X-Total-Count"]) >= 241
        assert_workflow_form_resume(client, headers, base, model_id, config)
        asyncio.run(reconcile_automation_notifications(config))
        print(
            "AUTOMATIONS_POSTGRES_OK: concurrent schedules, receipts, FIFO dispatch, notifications, pagination, workflow resume"
        )


if __name__ == "__main__":
    check()
