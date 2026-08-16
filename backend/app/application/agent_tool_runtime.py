"""Thin Agent bridge for the provider-neutral durable Tool runtime."""

import asyncio
import hashlib
import json
from datetime import timedelta
from typing import Any

from app.application.tool_runtime import (
    ToolInvocationBusy,
    ToolInvocationConflict,
    execute_tool_invocation,
    queue_tool_invocation,
)
from app.entities.agents import AgentRun
from app.entities.tools import ToolSnapshot
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.session import get_session_factory
from app.ports.tool_runtime import ToolInvocationContext, ToolRuntimeResult
from app.shareddomain.agents.runtime import (
    AgentExecutionPaused,
    AgentToolBusy,
    AgentToolResult,
    AgentToolUncertain,
)
from app.shareddomain.agents.runtime.state import PendingToolCall
from app.shareddomain.tools.runtime import TOOL_INVOCATION_AWAITING_APPROVAL


def agent_tool_invocation_identity(
    run_id: str,
    turn: int,
    call_id: str,
) -> tuple[str, str]:
    invocation_id = f"{turn}:{call_id}"
    if len(invocation_id) > 255:
        raise ValueError("Agent Tool invocation identity is too long.")
    identity = f"agent:{run_id}:{invocation_id}"
    return invocation_id, hashlib.sha256(identity.encode()).hexdigest()


def tool_runtime_result_to_agent_result(result: ToolRuntimeResult) -> AgentToolResult:
    if isinstance(result.data, str):
        content = result.data
    elif result.data is not None:
        content = json.dumps(result.data, ensure_ascii=False)
    else:
        content = result.error_message or result.summary
    return AgentToolResult(
        content=content,
        summary=result.summary,
        output=result.data,
        is_error=not result.ok,
        outcome_uncertain=result.outcome == "uncertain",
    )


class UnifiedAgentToolRuntime:
    """Executes frozen Agent Tool snapshots through ``ToolInvocation`` only."""

    def __init__(
        self,
        run: AgentRun,
        snapshots: list[ToolSnapshot],
        worker_task_id: str,
        settings: Settings,
        lease_lost: asyncio.Event,
    ) -> None:
        self.run = run
        self.snapshots = {snapshot.function_name: snapshot for snapshot in snapshots}
        if len(self.snapshots) != len(snapshots):
            raise ValueError("Agent Tool function names must be unique.")
        self.worker_task_id = worker_task_id
        self.settings = settings
        self.lease_lost = lease_lost

    async def before(
        self,
        turn: int,
        call: PendingToolCall,
        metadata: dict[str, str],
        arguments: dict[str, Any],
    ) -> AgentToolResult | None:
        del metadata
        snapshot = self.snapshots.get(call["name"])
        if snapshot is None:
            return None
        if self.lease_lost.is_set():
            raise AgentToolBusy(call["id"], "Agent run lease was lost.")

        invocation_id, idempotency_key = agent_tool_invocation_identity(
            self.run.id,
            turn,
            call["id"],
        )
        context = ToolInvocationContext(
            workspace_id=self.run.workspace_id,
            origin="agent",
            root_run_id=self.run.id,
            run_id=self.run.id,
            invocation_id=invocation_id,
            execution_user_id=self.run.execution_user_id,
            access_source=self.run.access_source,
            deadline_at=utc_now()
            + timedelta(seconds=self.settings.agent_tool_timeout_seconds),
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
            raise AgentToolUncertain(invocation_id, str(exc)) from exc
        except ValueError:
            return AgentToolResult(
                content="Tool parameters are invalid.",
                summary="Invalid tool parameters.",
                is_error=True,
            )

        if invocation.status == TOOL_INVOCATION_AWAITING_APPROVAL:
            raise AgentExecutionPaused(
                invocation_id,
                "Tool call requires user approval.",
            )
        try:
            result = await execute_tool_invocation(
                invocation.id,
                self.settings,
                f"{self.worker_task_id}:{invocation_id}",
            )
        except ToolInvocationBusy as exc:
            raise AgentToolBusy(call["id"], str(exc)) from exc
        mapped = tool_runtime_result_to_agent_result(result)
        if mapped.outcome_uncertain:
            raise AgentToolUncertain(
                invocation_id,
                result.error_message or result.summary or "Tool outcome is uncertain.",
            )
        if result.error_code == "approval_required":
            raise AgentExecutionPaused(
                invocation_id,
                "Tool call requires user approval.",
            )
        return mapped


__all__ = [
    "UnifiedAgentToolRuntime",
    "agent_tool_invocation_identity",
    "tool_runtime_result_to_agent_result",
]
