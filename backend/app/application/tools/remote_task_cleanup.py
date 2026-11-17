"""Recover idempotent remote cancellation after worker loss or local deletion."""

import asyncio
from datetime import timedelta

from app.domain.tools.mcp.service import resolved_mcp_server_connection
from app.domain.tools.mcp.task_contract import (
    REMOTE_TERMINAL,
    parse_task_status,
    server_binding,
)
from app.entities.defaults import new_id, utc_now
from app.infra.db.repositories.tools import mcp as mcp_repository
from app.infra.db.repositories.tools import remote_tasks as repository
from app.infra.db.session import get_session_factory
from app.ports.mcp import McpClientError, call_mcp_tool


async def _cancel(task, settings):
    error = None
    state, identity = task.status, task.remote_id
    try:
        if state == "ready":
            state = "failed"  # No submit request could have been dispatched.
        else:
            async with get_session_factory()() as db:
                server = await mcp_repository.get_mcp_server_by_id(db, task.server_id)
            if server is None:
                state = "orphaned"
                raise McpClientError(
                    "Remote task source was deleted; remote cancellation is unavailable.",
                    request_sent=False,
                )
            if (
                server.workspace_id != task.workspace_id
                or server.status != "active"
                or server_binding(server) != task.server_binding
            ):
                raise McpClientError(
                    "Remote task source is unavailable or changed.", request_sent=False
                )
            connection = await resolved_mcp_server_connection(server, settings)
            if identity is None:
                response = await call_mcp_tool(
                    connection,
                    settings,
                    task.contract["status_tool"],
                    {"request_id": task.request_key, "task_id": None},
                    idempotency_key=f"{task.id}:status",
                )
                if response.is_error:
                    raise McpClientError("Remote task lookup returned an error.")
                identity, state = parse_task_status(
                    response.structured_content, task.request_key
                )
            if state not in REMOTE_TERMINAL:
                response = await call_mcp_tool(
                    connection,
                    settings,
                    task.contract["cancel_tool"],
                    {"request_id": task.request_key, "task_id": identity},
                    idempotency_key=f"{task.id}:cancel",
                )
                if response.is_error:
                    raise McpClientError("Remote cancellation returned an error.")
                identity, state = parse_task_status(
                    response.structured_content, task.request_key, identity
                )
    except (McpClientError, ValueError):
        error = (
            "Remote cancellation has not been confirmed. Reconnect or restore the source to retry."
            if state != "orphaned"
            else "Source deleted; remote cancellation could not be confirmed."
        )
    async with get_session_factory()() as db:
        current = await repository.by_id(db, task.id, lock=True)
        if current is None or current.cancel_owner != task.cancel_owner:
            return
        current.remote_id = identity
        current.status = state
        current.last_error = error
        current.cancel_owner = None
        current.cancel_lease_until = None
        current.updated_at = utc_now()
        current.next_cancel_at = utc_now() + timedelta(
            seconds=min(3600, 3 * 2 ** min(current.cancel_attempts, 10))
        )
        await repository.save(db, current)
        await db.commit()


async def recover_remote_task_cancellations(settings):
    async with get_session_factory()() as db:
        due = await repository.due_cancellations(db, utc_now(), limit=4)
        for task in due:
            task.cancel_requested = True
            task.cancel_owner = new_id()
            task.cancel_lease_until = utc_now() + timedelta(
                seconds=6 * settings.mcp_request_timeout_seconds + 90
            )
            task.cancel_attempts += 1
            await repository.save(db, task)
        await db.commit()
    await asyncio.gather(*(_cancel(task, settings) for task in due))
