"""Atomic quota reservation and idempotent settlement in short transactions."""

from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.domain.governance.models import ModelUsageReservation, WorkspaceTokenMonth
from app.domain.platform.models import WorkspaceGovernance
from app.entities.defaults import APP_TIMEZONE_NAME, utc_now
from app.entities.governance import ModelUsageReservation as ReservationEntity
from app.infra.db.mapping import to_entity, to_orm
from app.ports.llm import ModelQuotaExceeded


async def reserve(db, workspace_id, model_id, identity, tokens):
    governance = await db.get(WorkspaceGovernance, workspace_id)
    limit = governance.monthly_token_limit if governance else None
    period = (
        utc_now()
        .astimezone(ZoneInfo(governance.timezone if governance else APP_TIMEZONE_NAME))
        .strftime("%Y-%m")
    )
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    await db.execute(
        insert(WorkspaceTokenMonth)
        .values(
            workspace_id=workspace_id,
            period=period,
            used_tokens=0,
            reserved_tokens=0,
        )
        .on_conflict_do_nothing(index_elements=["workspace_id", "period"])
    )
    statement = update(WorkspaceTokenMonth).where(
        WorkspaceTokenMonth.workspace_id == workspace_id,
        WorkspaceTokenMonth.period == period,
    )
    if limit is not None:
        statement = statement.where(
            WorkspaceTokenMonth.used_tokens
            + WorkspaceTokenMonth.reserved_tokens
            + tokens
            <= limit
        )
    changed = await db.execute(
        statement.values(reserved_tokens=WorkspaceTokenMonth.reserved_tokens + tokens)
    )
    if changed.rowcount != 1:
        raise ModelQuotaExceeded()
    db.add(
        to_orm(
            ModelUsageReservation,
            ReservationEntity(
                id=identity,
                workspace_id=workspace_id,
                period=period,
                model_id=model_id,
                reserved_tokens=tokens,
            ),
        )
    )
    await db.flush()
    return limit is not None


async def settle(db, identity, actual):
    record = await db.scalar(
        select(ModelUsageReservation)
        .where(ModelUsageReservation.id == identity)
        .with_for_update()
    )
    if record is None or record.state not in {"dispatched", "uncertain"}:
        return
    # A missing usage report or an interrupted request may already be billable.
    if actual is None:
        record.state = "uncertain"
        await db.flush()
        return
    changed = await db.execute(
        update(ModelUsageReservation)
        .where(
            ModelUsageReservation.id == identity,
            ModelUsageReservation.state.in_(("dispatched", "uncertain")),
        )
        .values(state="settled", charged_tokens=actual)
    )
    if changed.rowcount != 1:
        return
    await db.execute(
        update(WorkspaceTokenMonth)
        .where(
            WorkspaceTokenMonth.workspace_id == record.workspace_id,
            WorkspaceTokenMonth.period == record.period,
        )
        .values(
            used_tokens=WorkspaceTokenMonth.used_tokens + actual,
            reserved_tokens=WorkspaceTokenMonth.reserved_tokens
            - record.reserved_tokens,
        )
    )


async def get_reservation(db, identity):
    record = await db.get(ModelUsageReservation, identity)
    return to_entity(ReservationEntity, record) if record else None
