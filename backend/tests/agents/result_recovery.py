"""Retained MCP results: atomic ledger writes, identity isolation and resume."""

import asyncio
import importlib.util
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa
import tests.support  # noqa: F401
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langchain_core.messages import ToolMessage
from mcp.types import Tool as McpTool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.agents.evaluation import ScriptedModel, answer_message, tool_message
from tests.support import settings

from app.application.agents.runs.executor import DurableToolLedger
from app.application.agents.tools.builder import (
    build_mcp_agent_tool,
    set_agent_tool_idempotency_key,
)
from app.application.agents.tools.results import read_run_tool_result
from app.application.tools.runtime.adapters.mcp import McpToolAdapter
from app.application.tools.runtime.contracts import ToolInvocationContext
from app.application.tools.runtime.service import (
    execute_tool_invocation,
    queue_tool_invocation,
)
from app.domain.agents.runtime import run_agent
from app.domain.agents.runtime.capabilities import CapabilityRegistry
from app.domain.agents.runtime.extensions import ExtensionRuntime
from app.domain.agents.runtime.session import AgentSession
from app.domain.tools.mcp.service import ResolvedMcpTool
from app.domain.tools.models import ToolInvocation as ToolInvocationOrm
from app.entities.defaults import utc_now
from app.entities.runs import AgentRun
from app.entities.tools import McpServer, ToolSnapshot
from app.infra.db.base import Base
from app.infra.db.repositories.tools import invocations
from app.ports.mcp import MAX_MCP_RESULT_BYTES, McpCallResult


async def assert_retained_mcp_results() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        run = AgentRun(
            id="run-1",
            workspace_id="ws-1",
            execution_user_id="user-1",
            access_source="console",
            root_run_id="run-1",
        )
        context = ToolInvocationContext(
            workspace_id=run.workspace_id,
            origin="agent",
            root_run_id=run.id,
            run_id=run.id,
            invocation_id="1:query",
            execution_user_id=run.execution_user_id,
            access_source=run.access_source,
            deadline_at=utc_now() + timedelta(minutes=5),
            idempotency_key="retained-result-1",
        )
        snapshot = ToolSnapshot(
            schema_version=1,
            tool_id="tool-1",
            version_id="v1",
            source_id="source-1",
            kind="mcp",
            function_name="query",
            display_name="Query",
            description="Query",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            output_schema=None,
            definition_hash="hash",
            policy_id="policy-1",
            policy_revision=1,
            bound_by_user_id=run.execution_user_id,
            approval="auto",
            effect="external_read",
            allowed_access_sources=("console",),
            workflow_callable=True,
            parallel_safe=True,
            execution_spec={"tool_name": "query"},
        )
        response = McpCallResult(
            content=[{"type": "text", "text": "查询😀\n" * 6000}],
            structured_content={"rows": [{"last": "tail-value"}]},
            meta={"original_cursor": "cursor"},
        )
        port = AsyncMock(return_value=response)
        with (
            patch(
                "app.application.tools.runtime.service.get_session_factory",
                return_value=factory,
            ),
            patch(
                "app.application.agents.tools.results.get_session_factory",
                return_value=factory,
            ),
            patch(
                "app.application.tools.runtime.service._validate_live_state",
                AsyncMock(return_value=(None, None)),
            ),
            patch("app.application.tools.runtime.adapters.mcp.mcp_server_connection"),
            patch("app.application.tools.runtime.adapters.mcp.call_mcp_tool", port),
        ):
            async with factory() as db:
                invocation = await queue_tool_invocation(db, snapshot, {}, context)
                await db.commit()
            adapter = McpToolAdapter(settings(), McpServer())
            result = await execute_tool_invocation(
                invocation.id, settings(), "worker-1", adapter=adapter
            )
            assert result.ok and result.data["result_id"] == context.idempotency_key
            assert (
                len(json.dumps(result.data, ensure_ascii=False).encode())
                <= MAX_MCP_RESULT_BYTES
            )
            async with factory() as db:
                stored = await invocations.get_tool_invocation_by_id(db, invocation.id)
            assert (
                stored.status == "succeeded"
                and json.loads(stored.full_result) == response.payload()
            )
            assert result.full_result == stored.full_result
            cached = await execute_tool_invocation(
                invocation.id, settings(), "new-worker", adapter=adapter
            )
            assert cached == result
            port.assert_awaited_once()
            await _assert_legacy_result(factory, run, response)

            offset, parts = 0, []
            while True:
                page = await read_run_tool_result(
                    run, context.idempotency_key, offset, 12000
                )
                assert (
                    not page.is_error
                    and len(page.content.encode()) <= MAX_MCP_RESULT_BYTES
                )
                parts.append(page.output["content"])
                if page.output["next_offset"] is None:
                    break
                assert page.output["next_offset"] > offset
                offset = page.output["next_offset"]
            assert "".join(parts) == stored.full_result
            assert (await read_run_tool_result(run, "missing", 0, 4000)).is_error
            for change in (
                {"workspace_id": "other"},
                {"id": "other"},
                {"execution_user_id": "other"},
                {"access_source": "public"},
            ):
                denied = await read_run_tool_result(
                    replace(run, **change), context.idempotency_key, 0, 4000
                )
                assert denied.is_error and "tail-value" not in denied.content
            for offset, limit in ((-1, 10), (0, 0), (0, 12001), (True, 10)):
                try:
                    await read_run_tool_result(
                        run, context.idempotency_key, offset, limit
                    )
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid read range was accepted")
            eof = await read_run_tool_result(
                run, context.idempotency_key, len(stored.full_result), 10
            )
            assert eof.output["content"] == "" and eof.output["next_offset"] is None

            async def reader(result_id, offset, limit):
                return await read_run_tool_result(run, result_id, offset, limit)

            def registry():
                return CapabilityRegistry(
                    ExtensionRuntime([]), [], result_reader=reader
                )

            catalog = registry()
            read_call = tool_message("read_tool_result", "read-tail")
            read_call.tool_calls[0]["args"] = {
                "result_id": context.idempotency_key,
                "offset": len(stored.full_result) - 300,
                "limit": 12000,
            }
            checkpoints = []

            class Interrupted(Exception):
                pass

            async def checkpoint(state, phase):
                if phase == "tool":
                    checkpoints.append(state)
                    raise Interrupted()

            try:
                await run_agent(
                    ScriptedModel([read_call]),
                    [{"role": "user", "content": "Read the tail"}],
                    catalog.tools,
                    session=AgentSession(catalog),
                    on_checkpoint=checkpoint,
                )
            except Interrupted:
                pass
            else:
                raise AssertionError("The checkpoint interruption was not reached")
            fresh_catalog = registry()
            resumed_model = ScriptedModel([answer_message("Tail recovered")])
            completed = await run_agent(
                resumed_model,
                [{"role": "user", "content": "Read the tail"}],
                fresh_catalog.tools,
                session=AgentSession(fresh_catalog),
                checkpoint=checkpoints[-1],
            )
            assert completed.content == "Tail recovered"
            tool_outputs = [
                item
                for item in resumed_model.requests[0]
                if isinstance(item, ToolMessage)
            ]
            assert "tail-value" in tool_outputs[-1].content
            port.assert_awaited_once()

            # A former worker cannot attach a body after another worker takes ownership.
            async with factory() as db:
                pending = await queue_tool_invocation(
                    db,
                    snapshot,
                    {},
                    replace(
                        context,
                        invocation_id="2:query",
                        idempotency_key="stale-worker-result",
                    ),
                )
                await invocations.claim_tool_invocation(
                    db,
                    run.workspace_id,
                    pending.id,
                    "current-worker",
                    utc_now(),
                    utc_now() + timedelta(minutes=1),
                )
                pending.status, pending.full_result = "succeeded", "stale body"
                assert not await invocations.finalize_tool_invocation(
                    db,
                    run.workspace_id,
                    pending.id,
                    "former-worker",
                    pending,
                )
                await db.commit()
            async with factory() as db:
                fenced = await invocations.get_tool_invocation_by_id(db, pending.id)
            assert fenced.status == "running" and fenced.full_result is None

            port.return_value = replace(response, is_error=True)
            async with factory() as db:
                error_invocation = await queue_tool_invocation(
                    db,
                    snapshot,
                    {},
                    replace(
                        context,
                        invocation_id="3:query",
                        idempotency_key="error-result",
                    ),
                )
                await db.commit()
            failed = await execute_tool_invocation(
                error_invocation.id, settings(), "worker-2", adapter=adapter
            )
            assert not failed.ok and failed.data["isError"]
            assert not (
                await read_run_tool_result(run, "error-result", 0, 100)
            ).is_error
            async with factory() as db:
                await db.execute(
                    sa.delete(ToolInvocationOrm).where(
                        ToolInvocationOrm.run_id == run.id
                    )
                )
                await db.commit()
            assert (
                await read_run_tool_result(run, context.idempotency_key, 0, 100)
            ).is_error
    finally:
        await engine.dispose()


async def _assert_legacy_result(
    factory, run: AgentRun, response: McpCallResult
) -> None:
    tool = ResolvedMcpTool(
        server=McpServer(workspace_id=run.workspace_id, name="Legacy server"),
        definition=McpTool(name="query", inputSchema={"type": "object"}),
    )
    async with factory() as db:
        db.add(
            ToolInvocationOrm(
                workspace_id=run.workspace_id,
                origin="agent",
                root_run_id=run.id,
                run_id=run.id,
                invocation_id="4:legacy-query",
                execution_user_id=run.execution_user_id,
                access_source=run.access_source,
                policy_snapshot={
                    "ledger_kind": "agent_internal_v1",
                    "internal_tool": {"turn": 4, "call_id": "legacy-query"},
                },
                arguments={},
                arguments_hash="0" * 64,
                idempotency_key="legacy-result",
                status="running",
                worker_task_id="legacy-worker",
            )
        )
        await db.commit()
    port = AsyncMock(return_value=response)
    with (
        patch(
            "app.application.agents.tools.builder.get_session_factory",
            return_value=factory,
        ),
        patch(
            "app.application.agents.runs.executor.get_session_factory",
            return_value=factory,
        ),
        patch(
            "app.application.agents.tools.builder.resolve_mcp_tools",
            AsyncMock(return_value=[tool]),
        ),
        patch("app.application.agents.tools.builder.mcp_server_connection"),
        patch("app.application.agents.tools.builder.call_mcp_tool", port),
    ):
        set_agent_tool_idempotency_key("legacy-result")
        result = await build_mcp_agent_tool(tool, settings(), "app-1").ainvoke({})
        assert not result.is_error and result.output["result_id"] == "legacy-result"
        ledger = DurableToolLedger(run, "legacy-worker", settings(), asyncio.Event())
        await ledger.after(4, {"id": "legacy-query"}, {}, {}, result)
        port.assert_awaited_once()
    async with factory() as db:
        stored = await db.scalar(
            sa.select(ToolInvocationOrm).where(
                ToolInvocationOrm.idempotency_key == "legacy-result"
            )
        )
    assert stored.status == "succeeded"
    assert json.loads(stored.full_result) == response.payload()
    page = await read_run_tool_result(run, "legacy-result", 0, 12000)
    assert not page.is_error
    assert page.output["content"] == stored.full_result[: page.output["next_offset"]]


async def assert_tool_result_migration() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/202610250002_tool_full_results.py"
    )
    spec = importlib.util.spec_from_file_location("tool_result_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:

            def check(sync):
                sync.exec_driver_sql(
                    "CREATE TABLE tool_invocations (id TEXT PRIMARY KEY, result_data TEXT)"
                )
                sync.exec_driver_sql(
                    "INSERT INTO tool_invocations VALUES ('existing', 'preview')"
                )
                with patch.object(
                    migration, "op", Operations(MigrationContext.configure(sync))
                ):
                    migration.upgrade()
                    assert (
                        sync.exec_driver_sql(
                            "SELECT full_result FROM tool_invocations"
                        ).scalar()
                        is None
                    )
                    sync.exec_driver_sql(
                        "UPDATE tool_invocations SET full_result = 'retained'"
                    )
                    try:
                        migration.downgrade()
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError(
                            "Migration discarded retained result bodies"
                        )
                    sync.exec_driver_sql(
                        "UPDATE tool_invocations SET full_result = NULL"
                    )
                    migration.downgrade()
                    migration.upgrade()
                    assert (
                        sync.exec_driver_sql(
                            "SELECT result_data FROM tool_invocations"
                        ).scalar()
                        == "preview"
                    )

            await connection.run_sync(check)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(assert_retained_mcp_results())
    asyncio.run(assert_tool_result_migration())
    print("AGENT_RESULT_RECOVERY_OK")


if __name__ == "__main__":
    main()
