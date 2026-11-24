"""End-to-end integration tests for automations, reliability, recovery, and notifications."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import tests.support  # noqa: F401
from sqlalchemy import select
from tests.support import (
    activate_admin,
    auth_headers,
    create_active_user,
    settings,
    test_client,
)

from app.application.automations.scheduler import (
    process_due_automations,
    reconcile_automation_notifications,
    recover_pending_automation_executions,
)
from app.domain.agents.models import (
    AGENT_RUN_SUCCEEDED_STATUS,
    AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS,
    AgentRunState,
)
from app.domain.automations import sign_webhook_payload
from app.domain.notifications.models import UserNotification
from app.domain.tools.models import ToolInvocation
from app.domain.workflows.models import WorkflowRunDetail
from app.entities.defaults import utc_now
from app.infra.db.repositories.agents import repository as agent_repository
from app.infra.db.session import get_session_factory


def _simple_workflow_graph() -> dict:
    return {
        "schema_version": 1,
        "nodes": [
            {
                "id": "start",
                "type": "workflow",
                "position": {"x": 0, "y": 0},
                "data": {"title": "Start", "type": "start", "config": {}},
            },
            {
                "id": "form-1",
                "type": "workflow",
                "position": {"x": 200, "y": 0},
                "data": {
                    "title": "Confirm Env",
                    "type": "form-node",
                    "config": {
                        "form_field_list": [
                            {
                                "variable": "env",
                                "name": "Environment",
                                "type": "input",
                                "is_required": True,
                            }
                        ],
                        "form_content_format": "Confirm environment {{ form }}",
                        "is_result": True,
                    },
                },
            },
            {
                "id": "answer-1",
                "type": "workflow",
                "position": {"x": 400, "y": 0},
                "data": {
                    "title": "End",
                    "type": "end",
                    "config": {"outputs": {"result": "{{form-1.env}}"}},
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": "start",
                "target": "form-1",
                "sourceHandle": None,
                "targetHandle": None,
            },
            {
                "id": "e2",
                "source": "form-1",
                "target": "answer-1",
                "sourceHandle": None,
                "targetHandle": None,
            },
        ],
    }


def _seed_model(client, admin_token: str, workspace_id: str) -> str:
    with patch(
        "app.application.models.registry.test_model_connection",
        return_value={"ok": True},
    ):
        resp = client.post(
            f"/api/v1/workspaces/{workspace_id}/models",
            headers=auth_headers(admin_token),
            json={
                "name": "gpt-test",
                "provider": "model_deepseek_provider",
                "provider_type": "deepseek",
                "model_type": "LLM",
                "model_name": "deepseek-chat",
                "credential": {
                    "api_base": "https://api.example.invalid/v1",
                    "api_key": "sk-test-1234",
                },
            },
        )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _set_automation_next_run_at(automation_id: str, target_dt: datetime) -> None:
    from app.domain.automations.models import Automation as AutomationOrm

    async with get_session_factory()() as db:
        row = await db.get(AutomationOrm, automation_id)
        assert row is not None
        row.next_run_at = target_dt
        await db.commit()


async def _create_pause_tool_invocation(
    run_id: str, status_value: str
) -> tuple[str, str]:
    async with get_session_factory()() as db:
        run = await agent_repository.get_agent_run_by_id(db, run_id)
        assert run is not None
        state = await db.scalar(
            select(AgentRunState).where(AgentRunState.run_id == run_id)
        )
        assert state is not None
        deadline = utc_now() + timedelta(minutes=10)
        state.status = status_value
        state.execution_deadline_at = deadline
        state.updated_at = utc_now() - timedelta(minutes=3)
        call_id = "call-1"
        from app.domain.tools.runtime import tool_snapshot_payload
        from app.entities.tools import ToolSnapshot

        snapshot = ToolSnapshot(
            schema_version=1,
            tool_id="tool-web-fetch",
            version_id="ver-1",
            source_id="source-1",
            kind="builtin",
            function_name="web_fetch",
            display_name="Web Fetch",
            description="Fetch web page",
            input_schema={"type": "object"},
            output_schema={},
            definition_hash="h" * 64,
            policy_id="pol-1",
            policy_revision=1,
            bound_by_user_id=run.execution_user_id,
            approval="each_call",
            effect="external_read",
            allowed_access_sources=("console", "public", "automation"),
            workflow_callable=True,
            parallel_safe=True,
            execution_spec={"builtin": "web_fetch"},
        )
        inv = ToolInvocation(
            workspace_id=run.workspace_id,
            origin="agent",
            root_run_id=run.id,
            run_id=run.id,
            invocation_id=f"turn-1:{call_id}",
            execution_user_id=run.execution_user_id,
            access_source="automation",
            tool_id=None,
            tool_version_id=None,
            arguments={"url": "https://example.com"},
            arguments_hash=hashlib.sha256(b"url").hexdigest(),
            policy_snapshot={"tool_snapshot": tool_snapshot_payload(snapshot)},
            status="awaiting_approval",
            idempotency_key=f"auto-approval:{run.id}",
        )
        db.add(inv)
        await db.commit()
        return deadline.isoformat(), call_id


async def _pause_workflow_for_form(run_id: str) -> tuple[str, str]:
    async with get_session_factory()() as db:
        state = await db.scalar(
            select(AgentRunState).where(AgentRunState.run_id == run_id)
        )
        detail = await db.scalar(
            select(WorkflowRunDetail).where(WorkflowRunDetail.run_id == run_id)
        )
        assert state is not None and detail is not None
        orig_exec_dl = utc_now() + timedelta(minutes=12)
        orig_wf_dl = utc_now() + timedelta(minutes=12)
        state.status = AGENT_RUN_UNIFIED_AWAITING_INPUT_STATUS
        state.execution_deadline_at = orig_exec_dl
        state.updated_at = utc_now() - timedelta(minutes=4)
        state.checkpoint = {
            "workflow_form": {
                "runtime_node_id": "form-1",
                "content": "Confirm environment prod",
                "fields": [
                    {
                        "variable": "env",
                        "name": "Environment",
                        "type": "input",
                        "is_required": True,
                    }
                ],
            }
        }
        detail.deadline_at = orig_wf_dl
        await db.commit()
        return orig_exec_dl.isoformat(), orig_wf_dl.isoformat()


async def _complete_run(run_id: str, result_text: str) -> None:
    async with get_session_factory()() as db:
        state = await db.scalar(
            select(AgentRunState).where(AgentRunState.run_id == run_id)
        )
        assert state is not None
        state.status = AGENT_RUN_SUCCEEDED_STATUS
        state.result = result_text
        state.finished_at = utc_now()
        state.updated_at = utc_now()
        await db.commit()


def test_end_to_end_automations_lifecycle() -> None:
    runtime_settings = settings()
    with test_client() as client:
        admin_token, workspace_id = activate_admin(client)
        bob_id, bob_token = create_active_user(client, admin_token, "bob")
        assert (
            client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=auth_headers(admin_token),
                json={"user_id": bob_id, "role": "member"},
            ).status_code
            == 201
        )
        model_id = _seed_model(client, admin_token, workspace_id)

        agent_resp = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=auth_headers(admin_token),
            json={
                "name": "Ops Agent",
                "instructions": "Help with ops.",
                "model_id": model_id,
            },
        )
        assert agent_resp.status_code == 201, agent_resp.text
        agent_id = agent_resp.json()["id"]

        # Unpublished agent rejected for automation
        unpub_resp = client.post(
            f"/api/v1/workspaces/{workspace_id}/automations",
            headers=auth_headers(admin_token),
            json={
                "name": "Unpub Fail",
                "target_app_id": agent_id,
                "trigger_type": "daily",
                "trigger_config": {"hour": 9, "minute": 0},
                "input_config": {"mode": "text", "text": "Ping"},
            },
        )
        assert unpub_resp.status_code == 409, unpub_resp.text

        # Publish v1 then v2
        assert (
            client.patch(
                f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}",
                headers=auth_headers(admin_token),
                json={"published": True},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}",
                headers=auth_headers(admin_token),
                json={"instructions": "Help with ops v2.", "published": True},
            ).status_code
            == 200
        )
        versions_resp = client.get(
            f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/versions",
            headers=auth_headers(admin_token),
        )
        assert versions_resp.status_code == 200, versions_resp.text
        versions = versions_resp.json()["items"]
        assert len(versions) == 2
        v1_id = next(item["id"] for item in versions if item["version_number"] == 1)

        # Grant Bob view on Ops Agent so Bob can create an automation on it
        assert (
            client.put(
                f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/permissions/{bob_id}",
                headers=auth_headers(admin_token),
                json={"permission": "view"},
            ).status_code
            == 200
        )

        enqueued_run_ids: list[str] = []

        async def _fake_enqueue(run_id: str, *_args, **_kwargs) -> None:
            enqueued_run_ids.append(run_id)

        with (
            patch(
                "app.application.automations.service.enqueue_prepared_agent_run",
                side_effect=_fake_enqueue,
            ),
            patch(
                "app.application.workflows.runs.service.enqueue_agent_run",
                side_effect=_fake_enqueue,
            ),
            patch(
                "app.application.agents.runs.service.enqueue_prepared_agent_run",
                side_effect=_fake_enqueue,
            ),
        ):
            bob_auto = client.post(
                f"/api/v1/workspaces/{workspace_id}/automations",
                headers=auth_headers(bob_token),
                json={
                    "name": "Bob v1 Schedule",
                    "target_app_id": agent_id,
                    "publication_version_id": v1_id,
                    "approval_mode": "always_ask",
                    "trigger_type": "daily",
                    "trigger_config": {"hour": 9, "minute": 0},
                    "input_config": {"mode": "text", "text": "Daily check"},
                },
            )
            assert bob_auto.status_code == 201, bob_auto.text
            bob_auto_data = bob_auto.json()
            bob_auto_id = bob_auto_data["id"]
            assert bob_auto_data["target_version_number"] == 1
            assert bob_auto_data["publication_version_id"] == v1_id

            # Isolation check: Admin cannot access Bob's personal automation
            assert (
                client.get(
                    f"/api/v1/workspaces/{workspace_id}/automations/{bob_auto_id}",
                    headers=auth_headers(admin_token),
                ).status_code
                == 404
            )

            # Set next_run_at back 2 days + 1h -> Beat catch-up picks ONLY latest + missed=2,
            # and second overlapping Beat tick creates ZERO duplicate runs!
            now = datetime(2026, 11, 24, 2, 0, tzinfo=UTC)
            overdue = now - timedelta(days=2, hours=1)
            asyncio.run(_set_automation_next_run_at(bob_auto_id, overdue))
            created_execs_1 = asyncio.run(
                process_due_automations(runtime_settings, now=now)
            )
            created_execs_2 = asyncio.run(
                process_due_automations(
                    runtime_settings, now=now + timedelta(seconds=5)
                )
            )
            assert len(created_execs_1) == 1
            assert len(created_execs_2) == 0
            assert len(enqueued_run_ids) == 1
            exec_1_id = created_execs_1[0]
            run_1_id = enqueued_run_ids[0]

            detail = client.get(
                f"/api/v1/workspaces/{workspace_id}/automations/{bob_auto_id}/executions/{exec_1_id}",
                headers=auth_headers(bob_token),
            )
            assert detail.status_code == 200, detail.text
            assert detail.json()["missed_count_before"] == 2
            assert detail.json()["run_id"] == run_1_id
            assert detail.json()["agent_run"]["id"] == run_1_id

            # Serial check: while run_1 is active, forcing next_run_at due records skipped execution
            asyncio.run(
                _set_automation_next_run_at(bob_auto_id, now - timedelta(minutes=1))
            )
            skipped_execs = asyncio.run(
                process_due_automations(
                    runtime_settings, now=now + timedelta(minutes=2)
                )
            )
            assert len(skipped_execs) == 1
            skipped_detail = client.get(
                f"/api/v1/workspaces/{workspace_id}/automations/{bob_auto_id}/executions/{skipped_execs[0]}",
                headers=auth_headers(bob_token),
            ).json()
            assert skipped_detail["dispatch_status"] == "skipped"
            assert skipped_detail["run_id"] is None

            # Pause prevents manual execution -> 409, resume restores
            assert (
                client.post(
                    f"/api/v1/workspaces/{workspace_id}/automations/{bob_auto_id}/pause",
                    headers=auth_headers(bob_token),
                ).status_code
                == 200
            )
            assert (
                client.post(
                    f"/api/v1/workspaces/{workspace_id}/automations/{bob_auto_id}/execute",
                    headers=auth_headers(bob_token),
                ).status_code
                == 409
            )
            assert (
                client.post(
                    f"/api/v1/workspaces/{workspace_id}/automations/{bob_auto_id}/resume",
                    headers=auth_headers(bob_token),
                ).status_code
                == 200
            )

            # Awaiting approval notification + deduplication + approve preserves original deadline
            orig_deadline_iso, call_id = asyncio.run(
                _create_pause_tool_invocation(run_1_id, "awaiting_approval_v2")
            )
            assert (
                asyncio.run(reconcile_automation_notifications(runtime_settings)) == 1
            )
            assert (
                asyncio.run(reconcile_automation_notifications(runtime_settings)) == 0
            )

            unread = client.get(
                f"/api/v1/messages/unread-count?workspace_id={workspace_id}",
                headers=auth_headers(bob_token),
            )
            assert unread.status_code == 200
            assert unread.json()["count"] == 1
            msgs = client.get(
                f"/api/v1/messages?workspace_id={workspace_id}",
                headers=auth_headers(bob_token),
            ).json()
            assert len(msgs) == 1
            assert msgs[0]["kind"] == "notification"
            assert msgs[0]["event_type"] == "awaiting_approval"
            assert msgs[0]["execution_id"] == exec_1_id

            # Admin does NOT receive Bob's personal notification
            assert (
                client.get(
                    f"/api/v1/messages/unread-count?workspace_id={workspace_id}",
                    headers=auth_headers(admin_token),
                ).json()["count"]
                == 0
            )

            approved = client.post(
                f"/api/v1/workspaces/{workspace_id}/automations/{bob_auto_id}/executions/{exec_1_id}/tool-calls/{call_id}/approval",
                headers=auth_headers(bob_token),
                json={"approve": True},
            )
            assert approved.status_code == 200, approved.text

            async def _check_deadline() -> str:
                async with get_session_factory()() as db:
                    state = await db.scalar(
                        select(AgentRunState).where(AgentRunState.run_id == run_1_id)
                    )
                    assert state is not None and state.execution_deadline_at is not None
                    dl = state.execution_deadline_at
                    if dl.tzinfo is None:
                        dl = dl.replace(tzinfo=UTC)
                    return dl.isoformat()

            assert asyncio.run(_check_deadline()) == orig_deadline_iso

            # Complete run + artifact check (owner downloads, non-owner denied)
            asyncio.run(_complete_run(run_1_id, "Done!"))

            async def _create_art() -> str:
                from app.application.artifacts.service import create_generated_artifact

                async with get_session_factory()() as db:
                    link = await create_generated_artifact(
                        db,
                        runtime_settings,
                        workspace_id=workspace_id,
                        run_id=run_1_id,
                        idempotency_key=f"art:{run_1_id}",
                        artifact_format="txt",
                        filename="report.txt",
                        content=b"Report content",
                        invocation_id="inv-1",
                    )
                    await db.commit()
                    return link.artifact_id

            art_id = asyncio.run(_create_art())
            assert (
                asyncio.run(reconcile_automation_notifications(runtime_settings)) == 1
            )
            exec_with_art = client.get(
                f"/api/v1/workspaces/{workspace_id}/automations/{bob_auto_id}/executions/{exec_1_id}",
                headers=auth_headers(bob_token),
            ).json()
            assert len(exec_with_art["artifacts"]) == 1
            dl_url = exec_with_art["artifacts"][0]["download_url"]
            assert dl_url == f"/api/v1/artifacts/{art_id}/content"
            assert (
                client.get(dl_url, headers=auth_headers(bob_token)).status_code == 200
            )
            assert (
                client.get(dl_url, headers=auth_headers(admin_token)).status_code == 404
            )

            # Mark read & read-all
            notif_id = msgs[0]["id"]
            assert (
                client.post(
                    f"/api/v1/messages/{notif_id}/read?workspace_id={workspace_id}",
                    headers=auth_headers(bob_token),
                ).status_code
                == 204
            )
            assert (
                client.post(
                    f"/api/v1/messages/read-all?workspace_id={workspace_id}",
                    headers=auth_headers(bob_token),
                ).status_code
                == 204
            )
            assert (
                client.get(
                    f"/api/v1/messages/unread-count?workspace_id={workspace_id}",
                    headers=auth_headers(bob_token),
                ).json()["count"]
                == 0
            )

            # Permission revocation check -> next manual execute rejected!
            assert (
                client.delete(
                    f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/permissions/{bob_id}",
                    headers=auth_headers(admin_token),
                ).status_code
                == 204
            )
            # After revocation, Bob can no longer download the artifact either!
            assert client.get(dl_url, headers=auth_headers(bob_token)).status_code in {
                403,
                404,
            }
            revoked_exec = client.post(
                f"/api/v1/workspaces/{workspace_id}/automations/{bob_auto_id}/execute",
                headers=auth_headers(bob_token),
            )
            assert revoked_exec.status_code == 202
            assert revoked_exec.json()["dispatch_status"] == "rejected"
            assert revoked_exec.json()["run_id"] is None

        # Webhook automation: HMAC, replay, 409 conflict, 429 cap, rotation, crash recovery, unpublish block
        wh_resp = client.post(
            f"/api/v1/workspaces/{workspace_id}/automations",
            headers=auth_headers(admin_token),
            json={
                "name": "Incident Hook",
                "target_app_id": agent_id,
                "trigger_type": "webhook",
                "trigger_config": {"max_pending": 2},
                "input_config": {
                    "mode": "text",
                    "text": "Investigate",
                    "webhook_input_path": "msg",
                },
            },
        )
        assert wh_resp.status_code == 201, wh_resp.text
        wh_data = wh_resp.json()
        wh_id = wh_data["id"]
        wh_url = wh_data["webhook_url"]
        wh_secret = wh_data["webhook_secret"]
        assert wh_secret and wh_url
        assert "webhook_secret" not in (
            client.get(
                f"/api/v1/workspaces/{workspace_id}/automations/{wh_id}",
                headers=auth_headers(admin_token),
            ).json()
        )

        ts = str(int(utc_now().timestamp()))
        payload_1 = json.dumps({"msg": "CPU 99%"}).encode()
        assert (
            client.post(
                wh_url,
                content=payload_1,
                headers={
                    "Content-Type": "application/json",
                    "X-NexaFlow-Timestamp": ts,
                    "X-NexaFlow-Event-Id": "evt-1",
                    "X-NexaFlow-Signature": "sha256=" + ("a" * 64),
                },
            ).status_code
            == 401
        )

        sig_1 = sign_webhook_payload(wh_secret, ts, payload_1, "evt-1")
        ok_1 = client.post(
            wh_url,
            content=payload_1,
            headers={
                "Content-Type": "application/json",
                "X-NexaFlow-Timestamp": ts,
                "X-NexaFlow-Event-Id": "evt-1",
                "X-NexaFlow-Signature": sig_1,
            },
        )
        assert ok_1.status_code == 202, ok_1.text
        wh_exec_1 = ok_1.json()["execution_id"]

        # Exact replay -> 202 deduplicated=True
        replay_1 = client.post(
            wh_url,
            content=payload_1,
            headers={
                "Content-Type": "application/json",
                "X-NexaFlow-Timestamp": ts,
                "X-NexaFlow-Event-Id": "evt-1",
                "X-NexaFlow-Signature": sig_1,
            },
        )
        assert replay_1.status_code == 202
        assert replay_1.json()["deduplicated"] is True
        assert replay_1.json()["execution_id"] == wh_exec_1

        # Conflict -> 409
        payload_1b = json.dumps({"msg": "CPU 10%"}).encode()
        assert (
            client.post(
                wh_url,
                content=payload_1b,
                headers={
                    "Content-Type": "application/json",
                    "X-NexaFlow-Timestamp": ts,
                    "X-NexaFlow-Event-Id": "evt-1",
                    "X-NexaFlow-Signature": sign_webhook_payload(
                        wh_secret, ts, payload_1b, "evt-1"
                    ),
                },
            ).status_code
            == 409
        )

        # Queue 2nd item, 3rd returns 429
        payload_2 = json.dumps({"msg": "Disk full"}).encode()
        assert (
            client.post(
                wh_url,
                content=payload_2,
                headers={
                    "Content-Type": "application/json",
                    "X-NexaFlow-Timestamp": ts,
                    "X-NexaFlow-Event-Id": "evt-2",
                    "X-NexaFlow-Signature": sign_webhook_payload(
                        wh_secret, ts, payload_2, "evt-2"
                    ),
                },
            ).status_code
            == 202
        )
        payload_3 = json.dumps({"msg": "OOM"}).encode()
        assert (
            client.post(
                wh_url,
                content=payload_3,
                headers={
                    "Content-Type": "application/json",
                    "X-NexaFlow-Timestamp": ts,
                    "X-NexaFlow-Event-Id": "evt-3",
                    "X-NexaFlow-Signature": sign_webhook_payload(
                        wh_secret, ts, payload_3, "evt-3"
                    ),
                },
            ).status_code
            == 429
        )

        # Rotate secret -> old secret rejected
        rot = client.post(
            f"/api/v1/workspaces/{workspace_id}/automations/{wh_id}/webhook-secret/rotate",
            headers=auth_headers(admin_token),
        )
        assert rot.status_code == 200
        new_secret = rot.json()["webhook_secret"]
        assert new_secret != wh_secret
        assert (
            client.post(
                wh_url,
                content=payload_3,
                headers={
                    "Content-Type": "application/json",
                    "X-NexaFlow-Timestamp": ts,
                    "X-NexaFlow-Event-Id": "evt-4",
                    "X-NexaFlow-Signature": sign_webhook_payload(
                        wh_secret, ts, payload_3, "evt-3"
                    ),
                },
            ).status_code
            == 401
        )

        # Crash recovery between commit and enqueue
        enqueued_after_recovery: list[str] = []

        async def _fail_once(*_args, **_kwargs) -> None:
            raise RuntimeError("redis down")

        async def _ok_enqueue(run_id: str, *_args, **_kwargs) -> None:
            enqueued_after_recovery.append(run_id)

        from app.application.automations.service import dispatch_execution_by_id

        with patch(
            "app.application.automations.service.enqueue_prepared_agent_run",
            side_effect=_fail_once,
        ):
            asyncio.run(dispatch_execution_by_id(wh_exec_1, runtime_settings))

        mid = client.get(
            f"/api/v1/workspaces/{workspace_id}/automations/{wh_id}/executions/{wh_exec_1}",
            headers=auth_headers(admin_token),
        ).json()
        assert mid["dispatch_status"] == "pending_dispatch"
        committed_run_id = mid["run_id"]
        assert committed_run_id is not None

        with patch(
            "app.application.automations.service.enqueue_prepared_agent_run",
            side_effect=_ok_enqueue,
        ):
            asyncio.run(recover_pending_automation_executions(runtime_settings))

        assert enqueued_after_recovery == [committed_run_id]
        after = client.get(
            f"/api/v1/workspaces/{workspace_id}/automations/{wh_id}/executions/{wh_exec_1}",
            headers=auth_headers(admin_token),
        ).json()
        assert after["dispatch_status"] == "dispatched"
        assert after["run_id"] == committed_run_id

        # App unpublish ("应用下架") blocks next manual execution cleanly!
        asyncio.run(_complete_run(committed_run_id, "Done hook 1"))
        assert (
            client.patch(
                f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}",
                headers=auth_headers(admin_token),
                json={"published": False},
            ).status_code
            == 200
        )
        waiting = client.get(
            f"/api/v1/workspaces/{workspace_id}/automations/{wh_id}/executions",
            headers=auth_headers(admin_token),
        ).json()["items"]
        for item in waiting:
            if item["dispatch_status"] == "queued":
                client.post(
                    f"/api/v1/workspaces/{workspace_id}/automations/{wh_id}/executions/{item['id']}/cancel",
                    headers=auth_headers(admin_token),
                ).raise_for_status()
        takedown = client.post(
            f"/api/v1/workspaces/{workspace_id}/automations/{wh_id}/execute",
            headers=auth_headers(admin_token),
        )
        assert takedown.status_code == 202
        assert takedown.json()["dispatch_status"] == "rejected"

        # Workflow automation: awaiting_input form + deadline non-reset + cancel + notification
        wf_resp = client.post(
            f"/api/v1/workspaces/{workspace_id}/agents",
            headers=auth_headers(admin_token),
            json={
                "name": "Auto WF",
                "app_type": "workflow",
                "instructions": "Run workflow.",
                "model_id": model_id,
            },
        )
        assert wf_resp.status_code == 201, wf_resp.text
        wf_id = wf_resp.json()["id"]
        assert (
            client.put(
                f"/api/v1/workspaces/{workspace_id}/workflows/{wf_id}/definition",
                headers=auth_headers(admin_token),
                json={
                    "expected_revision": 1,
                    "graph": _simple_workflow_graph(),
                },
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/v1/workspaces/{workspace_id}/workflows/{wf_id}/publish",
                headers=auth_headers(admin_token),
            ).status_code
            == 201
        )
        wf_auto = client.post(
            f"/api/v1/workspaces/{workspace_id}/automations",
            headers=auth_headers(admin_token),
            json={
                "name": "WF Manual",
                "target_app_id": wf_id,
                "trigger_type": "weekly",
                "trigger_config": {"weekdays": [1, 5], "hour": 8, "minute": 30},
                "input_config": {"mode": "json", "json_payload": {"env": "prod"}},
            },
        )
        assert wf_auto.status_code == 201, wf_auto.text
        wf_auto_id = wf_auto.json()["id"]

        with (
            patch(
                "app.application.automations.service.enqueue_prepared_agent_run",
                side_effect=_ok_enqueue,
            ),
            patch(
                "app.application.workflows.runs.service.enqueue_agent_run",
                side_effect=_ok_enqueue,
            ),
        ):
            wf_exec = client.post(
                f"/api/v1/workspaces/{workspace_id}/automations/{wf_auto_id}/execute",
                headers=auth_headers(admin_token),
                json={"request_id": "req-wf-1"},
            )
            assert wf_exec.status_code == 202, wf_exec.text
            wf_exec_id = wf_exec.json()["id"]
            wf_run_id = wf_exec.json()["run_id"]
            assert wf_exec.json()["workflow_run"]["id"] == wf_run_id

            # Awaiting form input notification -> submit form preserves deadlines!
            wf_exec_dl, wf_detail_dl = asyncio.run(_pause_workflow_for_form(wf_run_id))
            assert (
                asyncio.run(reconcile_automation_notifications(runtime_settings)) >= 1
            )
            submitted = client.post(
                f"/api/v1/workspaces/{workspace_id}/automations/{wf_auto_id}/executions/{wf_exec_id}/form",
                headers=auth_headers(admin_token),
                json={"runtime_node_id": "form-1", "form_data": {"env": "prod"}},
            )
            assert submitted.status_code == 200, submitted.text

            async def _check_wf_deadlines() -> tuple[str, str]:
                async with get_session_factory()() as db:
                    state = await db.scalar(
                        select(AgentRunState).where(AgentRunState.run_id == wf_run_id)
                    )
                    detail = await db.scalar(
                        select(WorkflowRunDetail).where(
                            WorkflowRunDetail.run_id == wf_run_id
                        )
                    )
                    assert state is not None and detail is not None
                    s_dl = state.execution_deadline_at
                    d_dl = detail.deadline_at
                    if s_dl.tzinfo is None:
                        s_dl = s_dl.replace(tzinfo=UTC)
                    if d_dl.tzinfo is None:
                        d_dl = d_dl.replace(tzinfo=UTC)
                    return s_dl.isoformat(), d_dl.isoformat()

            assert asyncio.run(_check_wf_deadlines()) == (wf_exec_dl, wf_detail_dl)

            # Cancel workflow run + verify cancelled notification
            cancelled = client.post(
                f"/api/v1/workspaces/{workspace_id}/automations/{wf_auto_id}/executions/{wf_exec_id}/cancel",
                headers=auth_headers(admin_token),
            )
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["run_status"] == "cancelled"
            assert (
                asyncio.run(reconcile_automation_notifications(runtime_settings)) >= 1
            )

        # Delete Bob permanently -> removes Bob's personal notifications without FK errors
        assert (
            client.delete(
                f"/api/v1/admin/users/{bob_id}",
                headers=auth_headers(admin_token),
            ).status_code
            == 204
        )

        async def _count_bob_notifications() -> int:
            async with get_session_factory()() as db:
                rows = await db.scalars(
                    select(UserNotification.id).where(
                        UserNotification.user_id == bob_id
                    )
                )
                return len(rows.all())

        assert asyncio.run(_count_bob_notifications()) == 0

    print("AUTOMATIONS_API_OK")


def main() -> None:
    test_end_to_end_automations_lifecycle()


if __name__ == "__main__":
    main()
