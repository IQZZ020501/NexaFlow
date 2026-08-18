"""Durable continuation for Workflow Agent nodes."""

import json
from datetime import UTC
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agent_runs import prepare_agent_run
from app.application.tool_runtime import preflight_tool_snapshot
from app.application.workspace import build_workspace_context
from app.entities.agents import AgentPublicationVersion, AgentRun
from app.entities.tools import ToolSnapshot
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workflow as workflow_repository
from app.infrastructure.session import get_session_factory
from app.shareddomain.agents.models import (
    AGENT_RUN_AWAITING_CHILD_STATUSES,
    AGENT_RUN_CANCELLED_STATUS,
    AGENT_RUN_FAILED_STATUS,
    AGENT_RUN_SUCCEEDED_STATUS,
)
from app.shareddomain.agents.permissions import require_agent_view
from app.shareddomain.agents.publications import agent_publication_hash
from app.shareddomain.tools.runtime import tool_snapshot_from_payload

MAX_WORKFLOW_CHILDREN = 4
MAX_CHILD_TURNS = 4
MAX_CHILD_TOOL_CALLS = 6
SAFE_CHILD_EFFECTS = frozenset({"pure", "external_read"})


def _child_goal(value: Any) -> str:
    goal = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    goal = goal.strip()
    if not goal or len(goal) > 4000:
        raise ValueError("Workflow Agent input must contain 1 to 4000 characters.")
    return goal


async def _require_snapshot_binder(
    db: AsyncSession,
    workspace_id: str,
    snapshot: dict[str, Any],
) -> None:
    binder_id = snapshot.get("bound_by_user_id")
    if not isinstance(binder_id, str):
        raise ValueError("Workflow Agent binder is missing.")
    binder = await user_repository.get_user_by_id(db, binder_id)
    if binder is None or not binder.is_active:
        raise ValueError("Workflow Agent binder is unavailable.")
    try:
        context = await build_workspace_context(db, binder, workspace_id)
    except HTTPException as exc:
        raise ValueError("Workflow Agent binder is unavailable.") from exc
    target = await agent_repository.get_agent_by_id(db, str(snapshot.get("agent_id")))
    if (
        target is None
        or target.workspace_id != workspace_id
        or target.app_type != "agent"
        or target.status != "active"
        or not target.published
    ):
        raise ValueError("Workflow Agent is unavailable.")
    try:
        await require_agent_view(db, target, binder, context.membership_role)
    except HTTPException as exc:
        raise ValueError("Workflow Agent access was revoked.") from exc


async def _validated_snapshot_tools(
    db: AsyncSession,
    workspace_id: str,
    snapshot: dict[str, Any],
) -> tuple[AgentPublicationVersion, list[ToolSnapshot]]:
    version_id = snapshot.get("version_id")
    agent_id = snapshot.get("agent_id")
    if not isinstance(version_id, str) or not isinstance(agent_id, str):
        raise ValueError("Workflow Agent snapshot is invalid.")
    version = await agent_repository.get_agent_publication_version(
        db,
        workspace_id,
        version_id,
    )
    if (
        version is None
        or version.agent_id != agent_id
        or version.configuration_hash != snapshot.get("configuration_hash")
        or version.configuration_snapshot != snapshot.get("configuration_snapshot")
        or version.resource_snapshot != snapshot.get("resource_snapshot")
        or agent_publication_hash(
            version.configuration_snapshot,
            version.resource_snapshot,
        )
        != version.configuration_hash
    ):
        raise ValueError("Workflow Agent publication changed or is invalid.")
    tool_payloads = (
        version.resource_snapshot.get("tools", [])
        if isinstance(version.resource_snapshot, dict)
        else None
    )
    if not isinstance(tool_payloads, list):
        raise ValueError("Workflow Agent Tool snapshot is invalid.")
    await _require_snapshot_binder(db, workspace_id, snapshot)
    try:
        tools = [
            tool_snapshot_from_payload(item)
            for item in tool_payloads
        ]
    except ValueError as exc:
        raise ValueError("Workflow Agent Tool snapshot is invalid.") from exc
    if any(
        tool.approval != "auto" or tool.effect not in SAFE_CHILD_EFFECTS
        for tool in tools
    ):
        raise ValueError("Workflow Agent Tools must be automatic and read-only.")
    return version, tools


async def preflight_workflow_agent_snapshots(
    db: AsyncSession,
    workspace_id: str,
    snapshots: list[dict[str, Any]],
    *,
    execution_user_id: str,
    access_source: str,
) -> None:
    for snapshot in snapshots:
        _version, tools = await _validated_snapshot_tools(db, workspace_id, snapshot)
        for tool in tools:
            if await preflight_tool_snapshot(
                db,
                tool,
                origin="agent",
                workspace_id=workspace_id,
                execution_user_id=execution_user_id,
                access_source=access_source,
            ) is not None:
                raise ValueError("Workflow Agent Tool access was revoked.")


async def ensure_workflow_agent_child(
    db: AsyncSession,
    parent: AgentRun,
    parent_node_id: str,
    input_value: Any,
    snapshot: dict[str, Any],
    actor: User,
    workspace_role: str | None,
    *,
    deadline_at: str,
    remaining_model_tokens: int,
) -> AgentRun:
    if parent.depth != 0 or parent.root_run_id != parent.id:
        raise ValueError("Nested Agent runs are not allowed.")
    existing = await agent_repository.get_agent_child_run(
        db,
        parent.workspace_id,
        parent.id,
        parent_node_id,
    )
    if existing is not None:
        return existing
    if len(
        await agent_repository.list_agent_child_runs(
            db,
            parent.workspace_id,
            parent.id,
        )
    ) >= MAX_WORKFLOW_CHILDREN:
        raise ValueError("Workflow child Agent limit reached.")
    if remaining_model_tokens <= 0:
        raise ValueError("Workflow child Agent token budget exhausted.")

    version, _tools = await _validated_snapshot_tools(
        db,
        parent.workspace_id,
        snapshot,
    )
    agent_id = version.agent_id

    child, _model = await prepare_agent_run(
        db,
        parent.workspace_id,
        agent_id,
        _child_goal(input_value),
        actor,
        workspace_role,
        persist=False,
        conversation_id=new_id(),
        access_source=parent.access_source,
        consumer_id=parent.consumer_id,
        publication_version=version,
        allow_pinned_publication=True,
        authorized_by_parent=True,
    )
    child.root_run_id = parent.id
    child.parent_run_id = parent.id
    child.parent_node_id = parent_node_id
    child.depth = 1
    child.application_snapshot = {
        **child.application_snapshot,
        "runtime_limits": {
            "deadline_at": deadline_at,
            "max_turns": MAX_CHILD_TURNS,
            "max_tool_calls": MAX_CHILD_TOOL_CALLS,
            "max_model_tokens": remaining_model_tokens,
        },
    }
    return await agent_repository.save_agent_run(db, child)


async def _fail_expired_waiting_parent(
    db: AsyncSession,
    parent: AgentRun,
) -> bool:
    detail = await workflow_repository.get_run_detail(db, parent.id)
    if detail is None:
        return False
    deadline = detail.deadline_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if deadline > utc_now():
        return False
    return await agent_repository.fail_agent_run_waiting_for_child(
        db,
        parent.id,
        "Workflow deadline exceeded while waiting for an Agent node.",
        utc_now(),
    )


async def reconcile_workflow_agent_children(
    settings: Settings | None = None,
    *,
    child_run_id: str | None = None,
) -> list[str]:
    resumed: list[str] = []
    async with get_session_factory()() as db:
        if child_run_id is None:
            children = await agent_repository.list_terminal_children_for_waiting_parents(
                db
            )
        else:
            child = await agent_repository.get_agent_run_by_id(db, child_run_id)
            children = [child] if child is not None else []
        for child in children:
            if (
                child.parent_run_id is None
                or child.status
                not in {
                    AGENT_RUN_SUCCEEDED_STATUS,
                    AGENT_RUN_FAILED_STATUS,
                    AGENT_RUN_CANCELLED_STATUS,
                }
            ):
                continue
            parent = await agent_repository.get_agent_run_by_id(
                db,
                child.parent_run_id,
            )
            if parent is None or parent.status not in AGENT_RUN_AWAITING_CHILD_STATUSES:
                continue
            if await _fail_expired_waiting_parent(db, parent):
                continue
            if await agent_repository.queue_agent_run_from_child(db, parent.id):
                resumed.append(parent.id)
        await db.commit()
    if settings is not None:
        from app.application.agent_runs import enqueue_prepared_agent_run

        for parent_id in resumed:
            await enqueue_prepared_agent_run(parent_id, settings, unified=True)
    return resumed


__all__ = [
    "ensure_workflow_agent_child",
    "preflight_workflow_agent_snapshots",
    "reconcile_workflow_agent_children",
]
