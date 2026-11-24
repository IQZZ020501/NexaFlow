"""Deterministic ownership, renewal and image cancellation races on real rows."""

import asyncio
import base64
import json
import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.messages import AIMessage
from openai import AsyncOpenAI
from tests import support
from tests.agents.evaluation import ScriptedModel, answer_message
from tests.support import activate_admin, settings, test_client

from app.adapters.execution import opensandbox
from app.adapters.llm import image as image_adapter
from app.application.agents.tools.results import read_run_tool_result
from app.application.agents.tools.runtime import UnifiedAgentToolRuntime
from app.application.tools.runtime import service
from app.application.tools.runtime.adapters import image_generation, shell
from app.domain.agents.runtime import AgentToolResult, create_agent_tool, run_agent
from app.domain.models.registered import RegisteredModel
from app.domain.tools.runtime import build_tool_snapshot
from app.entities.agents import Agent
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.infra.db.repositories.agents import repository as runs
from app.infra.db.repositories.execution import sessions as execution_sessions
from app.infra.db.repositories.identity import users
from app.infra.db.repositories.tools import repository as tools
from app.infra.db.session import get_session_factory
from app.infra.execution.profile import execution_profile
from app.ports.tools import ToolInvocationContext, ToolRuntimeResult


async def fixture(workspace_id, *, image=False, approval_required=False):
    async with get_session_factory()() as db:
        actor = await users.get_active_user_by_username(db, "admin")
        model = RegisteredModel(
            workspace_id=workspace_id,
            name="Model " + str(utc_now()),
            provider="model_openai_provider",
            provider_type="openai_compatible",
            model_type="IMAGE" if image else "LLM",
            model_name="fixture",
            api_base="https://unused.example.com",
            created_by_user_id=actor.id,
            credential_config={},
            meta={},
            status="active",
        )
        db.add(model)
        await db.flush()
        application = await runs.create_agent(
            db,
            Agent(
                workspace_id=workspace_id,
                name="Owner " + model.id,
                model_id=model.id,
                created_by_user_id=actor.id,
            ),
        )
        run = await runs.create_agent_run(
            db,
            AgentRun(
                workspace_id=workspace_id,
                agent_id=application.id,
                requested_by_user_id=actor.id,
                execution_user_id=actor.id,
                configuration_source="draft",
                status="running_v2",
                worker_task_id="run-owner",
                lease_expires_at=utc_now() + timedelta(seconds=60),
                execution_deadline_at=utc_now() + timedelta(seconds=60),
                application_snapshot={"execution_profile": execution_profile(settings())},
            ),
        )
        tool = next(
            t
            for t in await tools.list_tools(db, workspace_id)
            if t.function_name == ("generate_image" if image else "bash")
        )
        source = await tools.get_tool_source(db, workspace_id, tool.source_id)
        version = await tools.get_tool_version(
            db, workspace_id, tool.current_version_id
        )
        policy = await tools.get_tool_policy(db, workspace_id, tool.id)
        snapshot = build_tool_snapshot(tool, source, version, policy, actor.id)
        invocation = await service.queue_tool_invocation(
            db,
            snapshot,
            {"prompt": "image"} if image else {"command": "true"},
            ToolInvocationContext(
                workspace_id=workspace_id,
                origin="agent",
                root_run_id=run.id,
                run_id=run.id,
                invocation_id="1:call",
                execution_user_id=actor.id,
                access_source="console",
                deadline_at=run.execution_deadline_at,
                idempotency_key=run.id,
                approval_required=approval_required,
                image_model_id=model.id if image else None,
            ),
        )
        await db.commit()
    return run, invocation, snapshot


async def cancel(run):
    async with get_session_factory()() as db:
        await runs.cancel_agent_run_tree(db, run.id, utc_now())
        await db.commit()


async def check_unconfirmed_creation_fails_without_resource_wait(workspace_id):
    run, invocation, snapshot = await fixture(workspace_id)
    config = replace(settings(), opensandbox_api_key="test-control-plane")
    platform = opensandbox.OpenSandboxExecution(config)
    platform.capacity.acquire = AsyncMock(return_value="held-slot")
    platform.capacity.release = AsyncMock()
    with (
        patch.object(shell, "build_execution_platform", return_value=platform),
        patch.object(
            opensandbox.Sandbox,
            "create",
            AsyncMock(side_effect=RuntimeError("SDK wrapped create failure")),
        ) as create,
    ):
        for turn in range(1, 4):
            if turn > 1:
                async with get_session_factory()() as db:
                    invocation = await service.queue_tool_invocation(
                        db,
                        snapshot,
                        {"command": "true"},
                        ToolInvocationContext(
                            workspace_id=workspace_id,
                            origin="agent",
                            root_run_id=run.id,
                            run_id=run.id,
                            invocation_id=f"{turn}:retry",
                            execution_user_id=run.execution_user_id,
                            access_source="console",
                            deadline_at=run.execution_deadline_at,
                            idempotency_key=f"{run.id}:{turn}",
                            approval_required=False,
                        ),
                    )
                    await db.commit()
            try:
                result = await service.execute_tool_invocation(
                    invocation.id,
                    config,
                    "tool-owner",
                    run_worker_task_id=run.worker_task_id,
                )
            except service.ToolInvocationBusy as exc:
                raise AssertionError(
                    "A failed sandbox creation paused the Agent for another 300 seconds"
                ) from exc
            assert not result.ok and result.outcome == "confirmed", result
            if turn > 1:
                assert "this Run" in result.error_message, result
            async with get_session_factory()() as db:
                row = await tools.get_tool_invocation_by_id(db, invocation.id)
                assert row.status == "failed" and not row.resource_wait
                sessions = await execution_sessions.for_run(db, workspace_id, run.id)
                assert len(sessions) == 1
                record = sessions[0]
                assert record.sandbox_id is None and record.creation_pending
                assert record.capacity_token == "held-slot"
            if turn == 2:
                # Background cleanup may mark the unresolved intent closing.
                await platform.close_session(workspace_id, run.id)

        knowledge = AsyncMock(
            return_value=AgentToolResult(content="Form fields", summary="Found")
        )
        runtime = UnifiedAgentToolRuntime(
            run, [snapshot], run.worker_task_id, config, asyncio.Event()
        )
        responses = [
            AIMessage(
                content="",
                tool_calls=[{"name": name, "id": name, "args": args}],
                response_metadata={"finish_reason": "tool_calls"},
            )
            for name, args in (("bash", {"command": "true"}), ("search_knowledge", {}))
        ]
        model = ScriptedModel([*responses, answer_message("Form fields")])
        fallback = await asyncio.wait_for(
            run_agent(
                model,
                [{"role": "user", "content": "What does the form contain?"}],
                [
                    create_agent_tool(
                        name="bash",
                        description="Execute a command",
                        parameters=snapshot.input_schema,
                        execute=AsyncMock(side_effect=AssertionError("Bypassed ledger")),
                    ),
                    create_agent_tool(
                        name="search_knowledge",
                        description="Search documents",
                        parameters={"type": "object", "properties": {}},
                        execute=knowledge,
                    ),
                ],
                before_tool_call=runtime.before,
            ),
            timeout=5,
        )
        assert fallback.content == "Form fields"
        assert any("this Run" in str(message.content) for message in model.requests[1])
        knowledge.assert_awaited_once()
        create.assert_awaited_once()
        platform.capacity.release.assert_not_awaited()


def success():
    return ToolRuntimeResult(True, {}, "Done", None, None, "confirmed", {})


async def check_renewal(workspace_id):
    run, invocation, _snapshot = await fixture(workspace_id)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def invoke(*_args):
        entered.set()
        await finish.wait()
        return success()

    config = replace(
        settings(),
        agent_executor_lease_seconds=2,
        agent_executor_heartbeat_seconds=0.02,
    )
    adapter = SimpleNamespace(kind="builtin", invoke=AsyncMock(side_effect=invoke))
    task = asyncio.create_task(
        service.execute_tool_invocation(
            invocation.id,
            config,
            "tool-owner",
            adapter=adapter,
            run_worker_task_id=run.worker_task_id,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        # A nearly expired claim must be extended while the provider is blocked.
        async with get_session_factory()() as db:
            row = await tools.get_tool_invocation_by_id(db, invocation.id)
            row.lease_expires_at = utc_now() + timedelta(seconds=0.1)
            await tools.save_tool_invocation(db, row)
            await db.commit()
        await asyncio.sleep(0.2)
        async with get_session_factory()() as db:
            taken = await tools.claim_tool_invocation(
                db,
                run.workspace_id,
                invocation.id,
                "replacement",
                utc_now(),
                utc_now() + timedelta(seconds=2),
            )
            await db.commit()
        assert not taken, (
            "A live ordinary invocation lost its lease and was dispatched twice"
        )
        finish.set()
        result = await asyncio.wait_for(task, 2)
        assert result.ok, result
        adapter.invoke.assert_awaited_once()
    finally:
        finish.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def check_ownership_loss(workspace_id, *, run_loss):
    run, invocation, _snapshot = await fixture(workspace_id)
    entered, interrupted = asyncio.Event(), asyncio.Event()
    observed = []

    async def invoke(_snapshot, _arguments, context):
        observed.append(context)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            interrupted.set()

    config = replace(settings(), agent_executor_heartbeat_seconds=0.02)
    task = asyncio.create_task(
        service.execute_tool_invocation(
            invocation.id,
            config,
            "tool-owner",
            adapter=SimpleNamespace(kind="builtin", invoke=invoke),
            run_worker_task_id=run.worker_task_id,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with get_session_factory()() as db:
            if run_loss:
                current = await runs.get_agent_run_by_id(db, run.id)
                current.worker_task_id = "new-run-owner"
                await runs.save_agent_run(db, current)
            else:
                row = await tools.get_tool_invocation_by_id(db, invocation.id)
                row.worker_task_id = "new-tool-owner"
                await tools.save_tool_invocation(db, row)
            await db.commit()
        await asyncio.wait_for(interrupted.wait(), 0.5)
        assert observed[0].ownership_lost.is_set()
        result = await asyncio.wait_for(task, 2)
        assert not result.ok
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def check_expired_result_without_takeover(workspace_id):
    run, invocation, _snapshot = await fixture(workspace_id)

    async def invoke(*_args):
        async with get_session_factory()() as db:
            row = await tools.get_tool_invocation_by_id(db, invocation.id)
            row.lease_expires_at = utc_now() - timedelta(seconds=1)
            await tools.save_tool_invocation(db, row)
            await db.commit()
        return success()

    result = await service.execute_tool_invocation(
        invocation.id,
        settings(),
        "owner",
        adapter=SimpleNamespace(kind="builtin", invoke=invoke),
        run_worker_task_id=run.worker_task_id,
    )
    assert result.ok, result


async def check_shell_log_paging(workspace_id):
    run, invocation, _snapshot = await fixture(workspace_id)
    response = {
        "ok": True,
        "exit_code": 7,
        "stdout": '"' * 10000,
        "stderr": "\\" * 10000,
        "artifacts": [],
        "truncated": False,
    }
    with (
        patch.object(
            shell,
            "build_execution_platform",
            return_value=SimpleNamespace(execute=AsyncMock(return_value=response)),
        ),
        patch.object(shell, "restore_conversation_files", AsyncMock()),
    ):
        result = await service.execute_tool_invocation(
            invocation.id,
            settings(),
            "shell-owner",
            run_worker_task_id=run.worker_task_id,
        )
    assert result.ok and result.data["exit_code"] == 7, result
    parts, offset = [], 0
    while True:
        page = await read_run_tool_result(run, result.data["result_id"], offset, 12000)
        assert not page.is_error
        assert len(page.content.encode()) <= 24 * 1024
        parts.append(page.output["content"])
        offset = page.output["next_offset"]
        if offset is None:
            break
    retained = json.loads("".join(parts))
    assert (
        retained["stdout"] == response["stdout"]
        and retained["stderr"] == response["stderr"]
    )
    denied = await read_run_tool_result(
        replace(run, execution_user_id="other"), run.id, 0, 100
    )
    assert denied.is_error


async def check_image_success(workspace_id):
    run, invocation, _snapshot = await fixture(workspace_id, image=True)

    async def record_started():
        async with get_session_factory()() as db:
            row = await tools.get_tool_invocation_by_id(db, invocation.id)
            assert row.status == "running" and row.attempts == 1

    started = AsyncMock(side_effect=record_started)

    async def generated(*_args):
        started.assert_awaited_once()
        return b"\x89PNG\r\n\x1a\nfixture"

    with patch.object(
        image_generation,
        "generate_image",
        AsyncMock(side_effect=generated),
    ) as provider:
        result = await service.execute_tool_invocation(
            invocation.id,
            settings(),
            "image-owner",
            run_worker_task_id=run.worker_task_id,
            on_started=started,
        )
        replay = await service.execute_tool_invocation(
            invocation.id, settings(), "replay", on_started=started
        )
    assert result.ok and replay.data["artifact_id"] == result.data["artifact_id"], (
        result
    )
    provider.assert_awaited_once()
    started.assert_awaited_once()
    async with get_session_factory()() as db:
        row = await tools.get_tool_invocation_by_id(db, invocation.id)
        assert (
            row.status == "succeeded"
            and row.policy_snapshot["dispatch_state"] == "completed"
        )

    _run, pending, _snapshot = await fixture(
        workspace_id, image=True, approval_required=True
    )
    awaiting = AsyncMock()
    result = await service.execute_tool_invocation(
        pending.id, settings(), "not-approved", on_started=awaiting
    )
    assert result.error_code == "approval_required"
    awaiting.assert_not_awaited()


async def check_image_result_survives_open_connection(workspace_id):
    run, invocation, _snapshot = await fixture(workspace_id, image=True)
    requests = []
    png = image_adapter.PNG_SIGNATURE + b"fixture"

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps({"data": [{"b64_json": base64.b64encode(png).decode()}]}).encode()
            await asyncio.Event().wait()

        async def aclose(self):
            pass

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            requests.append(request)
            return httpx.Response(200, stream=Body())

        async def aclose(self):
            await asyncio.Event().wait()

    def client(**options):
        return AsyncOpenAI(**options, http_client=httpx.AsyncClient(transport=Transport()))

    with (
        patch.object(image_adapter, "AsyncOpenAI", client),
        patch.object(image_adapter, "IMAGE_CLOSE_TIMEOUT_SECONDS", 0.01),
        patch.object(image_adapter, "_registered_model_credentials", return_value={
            "api_key": "fixture-only", "api_base": "https://image-fixture.invalid/v1",
        }),
    ):
        async with asyncio.timeout(2):
            result = await service.execute_tool_invocation(
                invocation.id, settings(), "image-receipt-owner",
                run_worker_task_id=run.worker_task_id,
            )
            replay = await service.execute_tool_invocation(invocation.id, settings(), "replay")
        if image_adapter._image_cleanup_tasks:
            await asyncio.gather(*list(image_adapter._image_cleanup_tasks))
    assert result.ok and result.outcome == "confirmed", result
    assert replay.data["artifact_id"] == result.data["artifact_id"]
    assert len(requests) == 1
    async with get_session_factory()() as db:
        row = await tools.get_tool_invocation_by_id(db, invocation.id)
        assert row.status == "succeeded" and row.policy_snapshot["dispatch_state"] == "completed"


async def check_image_recovery(workspace_id, *, dispatched):
    run, invocation, _snapshot = await fixture(workspace_id, image=True)
    async with get_session_factory()() as db:
        assert await tools.claim_tool_invocation(
            db,
            workspace_id,
            invocation.id,
            "dead-worker",
            utc_now() - timedelta(seconds=2),
            utc_now() - timedelta(seconds=1),
        )
        if dispatched:
            await tools.mark_tool_invocation_dispatch(db, invocation, "dispatched")
        await db.commit()
    with patch.object(
        image_generation,
        "generate_image",
        AsyncMock(return_value=b"\x89PNG\r\n\x1a\nfixture"),
    ) as provider:
        result = await service.execute_tool_invocation(
            invocation.id,
            settings(),
            "replacement",
            run_worker_task_id=run.worker_task_id,
        )
    assert result.ok is not dispatched, result
    assert provider.await_count == int(not dispatched)
    if dispatched:
        assert result.outcome == "uncertain"


async def check_image_cancellation(workspace_id, *, after_dispatch):
    run, invocation, _snapshot = await fixture(workspace_id, image=True)
    original_lookup = image_generation.model_repository.get_registered_model_by_id

    async def lookup(db, model_id):
        model = await original_lookup(db, model_id)
        if not after_dispatch:
            await cancel(run)
        return model

    async def provider(*_args):
        if after_dispatch:
            await cancel(run)
        return b"\x89PNG\r\n\x1a\nfixture"

    with (
        patch.object(
            image_generation.model_repository, "get_registered_model_by_id", lookup
        ),
        patch.object(
            image_generation, "generate_image", AsyncMock(side_effect=provider)
        ) as generate,
        patch.object(
            image_generation, "create_generated_artifact", AsyncMock()
        ) as store,
    ):
        result = await service.execute_tool_invocation(
            invocation.id,
            settings(),
            "image-owner",
            run_worker_task_id=run.worker_task_id,
        )
        assert not result.ok, result
        assert generate.await_count == int(after_dispatch), (
            "Cancelled Run sent a new billable request"
        )
        store.assert_not_awaited()
    async with get_session_factory()() as db:
        row = await tools.get_tool_invocation_by_id(db, invocation.id)
        assert row.outcome == ("uncertain" if after_dispatch else "confirmed")
        assert row.policy_snapshot["dispatch_state"] == (
            "dispatched" if after_dispatch else "not_started"
        )


def main():
    with tempfile.TemporaryDirectory(prefix="nexaflow-lifecycle-") as directory:
        runtime = replace(
            settings(),
            database_url=f"sqlite+aiosqlite:///{directory}/tests.db",
            knowledge_storage_dir=Path(directory) / "storage",
        )
        with (
            patch.object(support, "settings", return_value=runtime),
            test_client() as client,
        ):
            check_all(client)
    print("TOOL_LIFECYCLE_OK")


def check_all(client):
    _token, workspace_id = activate_admin(client)
    client.portal.call(check_unconfirmed_creation_fails_without_resource_wait, workspace_id)
    client.portal.call(check_renewal, workspace_id)
    client.portal.call(check_expired_result_without_takeover, workspace_id)
    client.portal.call(check_shell_log_paging, workspace_id)
    client.portal.call(check_image_success, workspace_id)
    client.portal.call(check_image_result_survives_open_connection, workspace_id)
    for run_loss in (True, False):

        async def ownership():
            await check_ownership_loss(workspace_id, run_loss=run_loss)

        client.portal.call(ownership)
    for after_dispatch in (False, True):

        async def image():
            await check_image_cancellation(workspace_id, after_dispatch=after_dispatch)

        client.portal.call(image)

        async def recovery():
            await check_image_recovery(workspace_id, dispatched=after_dispatch)

        client.portal.call(recovery)


if __name__ == "__main__":
    main()
