"""Durable host binding and reservation ledger, including ephemeral creation."""

from sqlalchemy import delete, or_, select, update

from app.domain.agents.models import AGENT_RUN_ACTIVE_STATUSES, AgentRunState
from app.domain.execution.models import ExecutionPlacement as Row
from app.domain.execution.models import ExecutionSession as SessionRow
from app.entities.execution import ExecutionPlacement, ExecutionSession
from app.infra.db.mapping import to_entity, to_orm


async def get(db, placement_id):
    row = await db.scalar(select(Row).where(Row.id == placement_id).with_for_update())
    return to_entity(ExecutionPlacement, row) if row else None


async def create(db, placement):
    db.add(to_orm(Row, placement))
    await db.flush()


async def active(db, now):
    rows = (
        await db.scalars(
            select(Row).where(Row.released.is_(False), Row.expires_at > now)
        )
    ).all()
    return [to_entity(ExecutionPlacement, row) for row in rows]


def capacity_record(placement):
    return ExecutionSession(
        id=placement.id,
        workspace_id=placement.workspace_id,
        run_id=placement.run_id or "",
        host_id=placement.host_id,
        host_fingerprint=placement.host_fingerprint,
        consumer_key=placement.consumer_key,
        expires_at=placement.expires_at,
        creation_pending=True,
        capacity_reservation={
            "id": placement.id,
            "profiles": placement.profiles,
            "member": "",
            "owner": "",
        },
    )


async def release(db, placement_id):
    await db.execute(update(Row).where(Row.id == placement_id).values(released=True))


async def releasable(db, now, host_id=None):
    rows = (
        await db.scalars(
            select(Row)
            .outerjoin(AgentRunState, AgentRunState.run_id == Row.run_id)
            .where(
                Row.released.is_(False),
                *([Row.host_id == host_id] if host_id else []),
                or_(
                    Row.expires_at <= now,
                    (
                        Row.run_id.is_not(None)
                        & or_(
                            AgentRunState.run_id.is_(None),
                            AgentRunState.execution_deadline_at <= now,
                            ~AgentRunState.status.in_(AGENT_RUN_ACTIVE_STATUSES),
                        )
                    ),
                ),
                ~select(SessionRow.id)
                .where(
                    SessionRow.workspace_id == Row.workspace_id,
                    SessionRow.run_id == Row.run_id,
                    SessionRow.state != "closed",
                )
                .exists(),
            )
            .limit(200)
        )
    ).all()
    return [to_entity(ExecutionPlacement, row) for row in rows]


async def prune_ephemeral(db, before):
    await db.execute(delete(Row).where(Row.run_id.is_(None), Row.released.is_(True), Row.expires_at <= before))
