"""Workflow bridge for the provider-neutral durable Tool runtime."""

import asyncio
from datetime import UTC
import hashlib
from typing import Any

from app.application.agent_tool_runtime import tool_runtime_result_to_agent_result
from app.application.tool_runtime import (
    ToolInvocationBusy,
    ToolInvocationConflict,
    execute_tool_invocation,
    queue_tool_invocation,
)
from app.entities.agents import AgentRun
from app.entities.tools import ToolSnapshot
from app.entities.workflows import WorkflowRunDetail
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.session import get_session_factory
from app.ports.tool_runtime import ToolInvocationContext
from app.shareddomain.agents.runtime import AgentToolResult
from app.shareddomain.tools.runtime import TOOL_INVOCATION_AWAITING_APPROVAL


def workflow_tool_invocation_identity(
    run_id: str,
    node_id: str,
    call_id: str,
) -> tuple[str, str]:
    invocation_id = f"{node_id}:{call_id}"
    if len(invocation_id) > 255:
        raise ValueError("Workflow Tool invocation identity is too long.")
    identity = f"workflow:{run_id}:{invocation_id}"
    return invocation_id, hashlib.sha256(identity.encode()).hexdigest()


class WorkflowToolRuntime:
    def __init__(
        self,
        run: AgentRun,
        detail: WorkflowRunDetail,
        snapshots: list[ToolSnapshot],
        worker_task_id: str,
        settings: Settings,
        lease_lost: asyncio.Event,
    ) -> None:
        self.run = run
        self.detail = detail
        self.worker_task_id = worker_task_id
        self.settings = settings
        self.lease_lost = lease_lost
        self.by_function = {item.function_name: item for item in snapshots}
        self.by_reference = {
            (item.tool_id, item.version_id): item for item in snapshots
        }
        if len(self.by_function) != len(snapshots):
            raise ValueError("Workflow Tool function names must be unique.")
        self.serial_lock = asyncio.Lock()

    def get_by_function(self, function_name: str) -> ToolSnapshot | None:
        return self.by_function.get(function_name)

    def get_by_reference(self, tool_id: str, version_id: str) -> ToolSnapshot:
        snapshot = self.by_reference.get((tool_id, version_id))
        if snapshot is None:
            raise ValueError("Workflow Tool snapshot is unavailable.")
        return snapshot

    async def invoke(
        self,
        snapshot: ToolSnapshot,
        node_id: str,
        call_id: str,
        arguments: dict[str, Any],
    ) -> AgentToolResult:
        if (
            call_id.startswith("llm:")
            and snapshot.execution_spec.get("direct_only") is True
        ):
            raise RuntimeError("This Workflow Tool can only be used as a direct node.")
        if snapshot.parallel_safe:
            return await self._invoke(snapshot, node_id, call_id, arguments)
        async with self.serial_lock:
            return await self._invoke(snapshot, node_id, call_id, arguments)

    async def _invoke(
        self,
        snapshot: ToolSnapshot,
        node_id: str,
        call_id: str,
        arguments: dict[str, Any],
    ) -> AgentToolResult:
        if self.lease_lost.is_set():
            raise RuntimeError("Workflow run lease was lost.")
        invocation_id, idempotency_key = workflow_tool_invocation_identity(
            self.run.id,
            node_id,
            call_id,
        )
        deadline_at = self.detail.deadline_at
        if deadline_at.tzinfo is None:
            deadline_at = deadline_at.replace(tzinfo=UTC)
        context = ToolInvocationContext(
            workspace_id=self.run.workspace_id,
            origin="workflow",
            root_run_id=self.run.id,
            run_id=self.run.id,
            invocation_id=invocation_id,
            execution_user_id=self.run.execution_user_id,
            access_source=self.run.access_source,
            deadline_at=deadline_at,
            idempotency_key=idempotency_key,
        )
        try:
            async with get_session_factory()() as db:
                invocation = await queue_tool_invocation(
                    db,
                    snapshot,
                    arguments,
                    context,
                )
                await db.commit()
        except ToolInvocationConflict as exc:
            raise RuntimeError(str(exc)) from exc
        except ValueError as exc:
            return AgentToolResult(
                content=f"Tool parameters are invalid. {exc}",
                summary="Invalid tool parameters.",
                is_error=True,
            )
        if invocation.status == TOOL_INVOCATION_AWAITING_APPROVAL:
            raise RuntimeError("Workflow Tools cannot require approval.")
        while True:
            try:
                result = await execute_tool_invocation(
                    invocation.id,
                    self.settings,
                    f"{self.worker_task_id}:{invocation_id}",
                )
                break
            except ToolInvocationBusy as exc:
                remaining = (deadline_at - utc_now()).total_seconds()
                if self.lease_lost.is_set() or remaining <= 0:
                    raise RuntimeError(str(exc)) from exc
                await asyncio.sleep(min(0.25, remaining))
        mapped = tool_runtime_result_to_agent_result(result)
        if mapped.outcome_uncertain:
            raise RuntimeError(
                result.error_message or result.summary or "Tool outcome is uncertain."
            )
        if result.error_code == "approval_required":
            raise RuntimeError("Workflow Tools cannot require approval.")
        return mapped


__all__ = ["WorkflowToolRuntime", "workflow_tool_invocation_identity"]
