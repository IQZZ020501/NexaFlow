"""Bounded wake grants lock Run before invocation, matching execution fencing."""

from datetime import timedelta

from sqlalchemy import or_, select, update

from app.domain.agents.models import (
    AGENT_RUN_LEGACY_CLAIMABLE_STATUSES,
    AGENT_RUN_UNIFIED_CLAIMABLE_STATUSES,
    AgentRunState,
)
from app.domain.tools.models import ToolInvocation
from app.domain.tools.runtime import TOOL_INVOCATION_QUEUED
from app.infra.db.repositories.execution.sessions import aware


def _grant(invocation, now):
    wait = invocation.resource_wait
    if not isinstance(wait, dict) or not wait:
        return False
    from datetime import datetime

    previous = wait.get("woken_at")
    if previous:
        try:
            if aware(datetime.fromisoformat(previous)) > now - timedelta(seconds=5):
                return False
        except (ValueError, TypeError):
            return False
    invocation.resource_wait = {
        **wait,
        "next_attempt_at": now.isoformat(),
        "woken_at": now.isoformat(),
    }
    return True


async def grant_waiters(db, now):
    waiting = (
        select(ToolInvocation.id)
        .where(
            ToolInvocation.run_id == AgentRunState.run_id,
            ToolInvocation.status == TOOL_INVOCATION_QUEUED,
            ToolInvocation.error_code == "tool_resource_wait",
        )
        .exists()
    )
    states = (
        await db.scalars(
            select(AgentRunState)
            .where(
                AgentRunState.status.in_(
                    (
                        *AGENT_RUN_LEGACY_CLAIMABLE_STATUSES,
                        *AGENT_RUN_UNIFIED_CLAIMABLE_STATUSES,
                    )
                ),
                or_(
                    AgentRunState.lease_expires_at.is_(None),
                    AgentRunState.lease_expires_at <= now,
                ),
                waiting,
            )
            .order_by(AgentRunState.updated_at, AgentRunState.run_id)
            .limit(50)
            .with_for_update(of=AgentRunState, skip_locked=True)
        )
    ).all()
    runs = []
    for state in states:
        invocations = (
            await db.scalars(
                select(ToolInvocation)
                .where(
                    ToolInvocation.run_id == state.run_id,
                    ToolInvocation.status == TOOL_INVOCATION_QUEUED,
                    ToolInvocation.error_code == "tool_resource_wait",
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
        granted = [_grant(invocation, now) for invocation in invocations]
        if any(granted):
            await db.execute(
                update(AgentRunState)
                .where(AgentRunState.run_id == state.run_id)
                .values(redispatched_at=now, updated_at=AgentRunState.updated_at)
            )
            runs.append((state.run_id, state.worker_generation))
    tests = []
    invocations = (
        await db.scalars(
            select(ToolInvocation)
            .where(
                ToolInvocation.run_id.is_(None),
                ToolInvocation.origin == "test",
                ToolInvocation.status == TOOL_INVOCATION_QUEUED,
                ToolInvocation.error_code == "tool_resource_wait",
            )
            .order_by(ToolInvocation.updated_at, ToolInvocation.id)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for invocation in invocations:
        if _grant(invocation, now):
            tests.append(invocation.id)
    await db.flush()
    return runs, tests
