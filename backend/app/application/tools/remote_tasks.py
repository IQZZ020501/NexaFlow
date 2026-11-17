"""One approved tool invocation owns a durable remote job and its lifecycle."""

import asyncio
from dataclasses import replace
from datetime import UTC

from app.domain.tools.mcp.service import resolved_mcp_server_connection
from app.domain.tools.mcp.task_contract import (
    REMOTE_TERMINAL,
    parse_task_status,
    server_binding,
)
from app.entities.defaults import utc_now
from app.entities.mcp_tasks import McpRemoteTask
from app.infra.db.repositories.tools import remote_tasks as repository
from app.infra.db.session import get_session_factory
from app.ports.execution import execution_scope
from app.ports.mcp import McpCallResult, McpClientError, call_mcp_tool


class RemoteTaskOwnershipLost(McpClientError):
    pass


async def _owned(db, snapshot, context, settings):
    from app.application.tools.runtime.service import _validate_live_state

    invocation = await repository.owned_invocation(db, context, settings)
    if invocation is None:
        raise RemoteTaskOwnershipLost(
            "Remote task worker no longer owns the invocation."
        )
    error, server = await _validate_live_state(db, invocation, snapshot)
    if error:
        raise McpClientError("Remote task authorization is no longer valid.")
    return invocation, server


async def _begin(snapshot, context, settings):
    async with get_session_factory()() as db:
        invocation, server = await _owned(db, snapshot, context, settings)
        task = await repository.get(db, invocation.id, lock=True)
        if task is None:
            task = McpRemoteTask(
                invocation_id=invocation.id,
                workspace_id=context.workspace_id,
                server_id=server.id,
                server_binding=server_binding(server),
                request_key=context.idempotency_key,
                contract=dict(snapshot.execution_spec["long_task"]),
                deadline_at=context.deadline_at,
                status="ready",
            )
            task = await repository.save(db, task)
        if (
            task.server_id != server.id
            or task.server_binding != server_binding(server)
            or task.request_key != context.idempotency_key
            or task.contract != snapshot.execution_spec["long_task"]
        ):
            raise McpClientError(
                "Remote task identity does not match its authorized contract.",
                request_sent=False,
            )
        await db.commit()
        return task


async def _progress(snapshot, context, settings, task, *, status=None, remote_id=None):
    async with get_session_factory()() as db:
        invocation, _server = await _owned(db, snapshot, context, settings)
        current = await repository.by_id(db, task.id, lock=True)
        if current is None or current.cancel_requested:
            raise RemoteTaskOwnershipLost("Remote task cancellation was requested.")
        if remote_id is not None:
            if current.remote_id is not None and current.remote_id != remote_id:
                raise McpClientError("Remote task identity changed.")
            current.remote_id = remote_id
        if status is not None:
            current.status = status
        current.updated_at = utc_now()
        current = await repository.save(db, current)
        await repository.progress(db, invocation, current)
        await db.commit()
        return current


async def _connection(snapshot, context, settings):
    async with get_session_factory()() as db:
        _invocation, server = await _owned(db, snapshot, context, settings)
        await db.commit()
    return await resolved_mcp_server_connection(server, settings)


async def _heartbeat(snapshot, context, settings):
    while True:
        await asyncio.sleep(settings.agent_executor_heartbeat_seconds)
        async with get_session_factory()() as db:
            await _owned(db, snapshot, context, settings)
            await db.commit()


async def request_cancellation(task_id, *, remote_id=None):
    async with get_session_factory()() as db:
        task = await repository.by_id(db, task_id, lock=True)
        if task and task.status not in REMOTE_TERMINAL:
            # A late submit receipt is retained only for cleanup after ownership
            # is lost. It cannot finalize the old worker's invocation.
            if remote_id and task.remote_id is None:
                task.remote_id = remote_id
            if task.status == "ready":
                task.status = "failed"
            else:
                task.cancel_requested = True
            task.updated_at = utc_now()
            await repository.save(db, task)
            await db.commit()


def _receipt(result, task):
    if result.is_error:
        raise McpClientError("Remote task control operation returned an error.")
    try:
        return parse_task_status(
            result.structured_content, task.request_key, task.remote_id
        )
    except ValueError as exc:
        raise McpClientError(str(exc)) from exc


async def _drive(snapshot, arguments, context, settings, task):
    scope = execution_scope.get()
    received_id = None
    try:
        if task.status == "ready":
            connection = await _connection(snapshot, context, settings)
            task = await _progress(
                snapshot, context, settings, task, status="submitting"
            )
            if scope:
                scope.attempt.unconfirmed = True
            try:
                response = await call_mcp_tool(
                    connection,
                    settings,
                    snapshot.execution_spec["tool_name"],
                    arguments,
                    idempotency_key=task.request_key,
                )
            except McpClientError as exc:
                if not exc.request_sent:
                    task = await _progress(
                        snapshot, context, settings, task, status="ready"
                    )
                    if scope:
                        scope.attempt.unconfirmed = False
                raise
            if response.is_error:
                task = await _progress(
                    snapshot, context, settings, task, status="failed"
                )
                if scope:
                    scope.attempt.unconfirmed = False
                return response
            received_id, state = _receipt(response, task)
            task = await _progress(
                snapshot, context, settings, task, status=state, remote_id=received_id
            )
            if scope:
                scope.attempt.unconfirmed = False
        while True:
            connection = await _connection(snapshot, context, settings)
            controls = {"request_id": task.request_key, "task_id": task.remote_id}
            if task.status not in REMOTE_TERMINAL:
                response = await call_mcp_tool(
                    connection,
                    settings,
                    task.contract["status_tool"],
                    controls,
                    idempotency_key=f"{task.id}:status",
                )
                received_id, state = _receipt(response, task)
                task = await _progress(
                    snapshot,
                    context,
                    settings,
                    task,
                    status=state,
                    remote_id=received_id,
                )
            if task.status in {"failed", "cancelled"}:
                return McpCallResult(
                    structured_content={
                        "request_id": task.request_key,
                        "task_id": task.remote_id,
                        "status": task.status,
                    },
                    content=[],
                    is_error=True,
                    meta={
                        "nexaflow/remoteTask": {
                            "id": task.id,
                            "task_id": task.remote_id,
                            "status": task.status,
                        }
                    },
                )
            if task.status == "succeeded":
                response = await call_mcp_tool(
                    connection,
                    settings,
                    task.contract["result_tool"],
                    {"request_id": task.request_key, "task_id": task.remote_id},
                    idempotency_key=f"{task.id}:result",
                )
                _identity, state = _receipt(response, task)
                if state != "succeeded":
                    raise McpClientError("Remote result is not terminal.")
                await _progress(snapshot, context, settings, task)
                return replace(
                    response,
                    meta={
                        **(response.meta or {}),
                        "nexaflow/remoteTask": {
                            "id": task.id,
                            "task_id": task.remote_id,
                            "status": state,
                        },
                    },
                )
            await asyncio.sleep(task.contract["poll_seconds"])
    except BaseException:
        if task.status != "ready":
            await asyncio.shield(request_cancellation(task.id, remote_id=received_id))
        raise


async def execute_remote_task(snapshot, arguments, context, settings):
    task = await _begin(snapshot, context, settings)
    work = asyncio.create_task(_drive(snapshot, arguments, context, settings, task))
    heartbeat = asyncio.create_task(_heartbeat(snapshot, context, settings))
    try:
        deadline = (
            task.deadline_at.replace(tzinfo=UTC)
            if task.deadline_at.tzinfo is None
            else task.deadline_at
        )
        async with asyncio.timeout(max(0.001, (deadline - utc_now()).total_seconds())):
            done, _pending = await asyncio.wait(
                {work, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
        if heartbeat in done:
            # Heartbeat failures fence the worker before another operation.
            await heartbeat
        return await work
    finally:
        work.cancel()
        heartbeat.cancel()
        await asyncio.gather(work, heartbeat, return_exceptions=True)
