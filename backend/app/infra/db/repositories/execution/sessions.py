from datetime import UTC, datetime

from sqlalchemy import or_, select, text, update

from app.domain.agents.models import (
    AGENT_RUN_ACTIVE_STATUSES,
    AGENT_RUN_RUNNING_STATUSES,
    AgentRun,
    AgentRunSnapshot,
    AgentRunState,
)
from app.domain.execution.models import ExecutionSession as Row
from app.domain.tools.execution import sandbox_requirements
from app.entities.execution import ExecutionRun, ExecutionSession
from app.infra.db.mapping import to_entity, to_orm
from app.infra.execution.profile import sandbox_resource_profile


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def run_for_execution(db, workspace_id, run_id):
    result = (
        await db.execute(
            select(AgentRunState, AgentRun, AgentRunSnapshot)
            .join(AgentRun, AgentRun.id == AgentRunState.run_id)
            .join(AgentRunSnapshot, AgentRunSnapshot.run_id == AgentRun.id)
            .where(
                AgentRunState.run_id == run_id,
                AgentRunState.workspace_id == workspace_id,
            )
            .with_for_update(of=AgentRunState)
        )
    ).first()
    if result is None:
        return None
    state, run, snapshot = result
    if (
        state.status not in AGENT_RUN_RUNNING_STATUSES
        or state.execution_deadline_at is None
    ):
        return None
    requirements = snapshot.application_snapshot.get("sandbox_requirements")
    if not isinstance(requirements, dict) or not requirements.get("profiles"):
        requirements = await sandbox_requirements(
            db, snapshot.tool_snapshots, snapshot.skill_snapshots, snapshot.mcp_tools
        )
    return (
        ExecutionRun(
            aware(state.execution_deadline_at),
            state.worker_task_id,
            run.access_source,
            run.consumer_id,
            sandbox_resource_profile(snapshot.tool_snapshots, snapshot.skill_snapshots),
            tuple(requirements["profiles"]),
        ),
        snapshot.application_snapshot.get("execution_profile"),
    )


async def live_session(db, workspace_id, run_id, purpose, owner_key):
    row = await db.scalar(
        select(Row)
        .where(
            Row.workspace_id == workspace_id,
            Row.run_id == run_id,
            Row.purpose == purpose,
            Row.owner_key == owner_key,
            Row.state != "closed",
        )
        .with_for_update()
    )
    return to_entity(ExecutionSession, row) if row else None


async def create(db, session):
    db.add(to_orm(Row, session))
    await db.flush()


async def lock_capacity(db, host_key):
    # One host-level transaction covers Redis admission and the durable create
    # intent. No OpenSandbox I/O happens under this lock.
    if db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:host, 0))"),
            {"host": host_key},
        )


async def capacity_records(db, now):
    rows = (
        await db.scalars(
            select(Row).where(
                Row.state != "closed",
                Row.expires_at > now,
                or_(
                    Row.capacity_token.is_not(None),
                    Row.sandbox_id.is_not(None),
                    Row.creation_pending.is_(True),
                ),
            )
        )
    ).all()
    from app.infra.db.repositories.execution import placements

    return [to_entity(ExecutionSession, row) for row in rows] + [
        placements.capacity_record(item) for item in await placements.active(db, now)
    ]


async def claim(db, session_id, holder, until, now):
    result = await db.execute(
        update(Row)
        .where(
            Row.id == session_id,
            Row.state.in_(("creating", "ready")),
            or_(Row.holder.is_(None), Row.holder_expires_at <= now),
        )
        .values(
            holder=holder, holder_expires_at=until, last_used_at=now, updated_at=now
        )
    )
    return result.rowcount == 1


async def update_owned(db, session, expected_holder, **values):
    result = await db.execute(
        update(Row)
        .where(
            Row.id == session.id,
            Row.holder == expected_holder,
            Row.state.in_(("creating", "ready")),
        )
        .values(**values)
    )
    return result.rowcount == 1


async def get(db, session_id):
    row = await db.get(Row, session_id)
    return to_entity(ExecutionSession, row) if row else None


async def for_run(db, workspace_id, run_id):
    rows = (
        await db.scalars(
            select(Row).where(
                Row.workspace_id == workspace_id,
                Row.run_id == run_id,
                Row.state != "closed",
            )
        )
    ).all()
    return [to_entity(ExecutionSession, row) for row in rows]


async def mark_closing(db, session_id):
    await db.execute(
        update(Row)
        .where(Row.id == session_id, Row.state != "closed")
        .values(state="closing")
    )


async def close_runs(db, run_ids):
    await db.execute(
        update(Row)
        .where(Row.run_id.in_(run_ids), Row.state != "closed")
        .values(state="closing")
    )


async def previous_session(db, workspace_id, run_id, purpose, owner_key):
    return await db.scalar(
        select(Row.id)
        .where(
            Row.workspace_id == workspace_id,
            Row.run_id == run_id,
            Row.purpose == purpose,
            Row.owner_key == owner_key,
        )
        .limit(1)
    )


async def mark_closed(db, session_id):
    await db.execute(
        update(Row)
        .where(Row.id == session_id)
        .values(
            state="closed",
            holder=None,
            holder_expires_at=None,
        )
    )


async def reclaimable(db, now):
    rows = (
        await db.scalars(
            select(Row)
            .outerjoin(AgentRunState, AgentRunState.run_id == Row.run_id)
            .where(
                Row.state != "closed",
                or_(
                    Row.state == "closing",
                    Row.expires_at <= now,
                    AgentRunState.execution_deadline_at <= now,
                    AgentRunState.run_id.is_(None),
                    ~AgentRunState.status.in_(AGENT_RUN_ACTIVE_STATUSES),
                ),
            )
            .limit(200)
        )
    ).all()
    return [to_entity(ExecutionSession, row) for row in rows]


async def tracked_sessions(db, host_id=None):
    return dict(
        (
            await db.execute(
                select(Row.id, Row.sandbox_id).where(
                    Row.state != "closed",
                    *([Row.host_id == host_id] if host_id else []),
                )
            )
        ).all()
    )
