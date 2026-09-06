from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.identity.enterprise import (
    EnterpriseIdentity,
    EnterpriseIdentityConnection,
    EnterpriseLoginState,
)
from app.infra.db import mapping
from app.domain.identity.enterprise.models import (
    EnterpriseIdentity as EnterpriseIdentityOrm,
    EnterpriseIdentityConnection as EnterpriseIdentityConnectionOrm,
    EnterpriseLoginState as EnterpriseLoginStateOrm,
)
from app.domain.platform.models import Workspace as WorkspaceOrm
from app.domain.platform.models import RefreshSession as RefreshSessionOrm


async def list_connections(
    db: AsyncSession, workspace_id: str, *, enabled_only: bool = False
) -> list[EnterpriseIdentityConnection]:
    statement = select(EnterpriseIdentityConnectionOrm).where(
        EnterpriseIdentityConnectionOrm.workspace_id == workspace_id
    )
    if enabled_only:
        statement = statement.where(EnterpriseIdentityConnectionOrm.enabled.is_(True))
    rows = await db.scalars(statement.order_by(EnterpriseIdentityConnectionOrm.provider))
    return [mapping.to_entity(EnterpriseIdentityConnection, row) for row in rows.all()]


async def list_enabled_connections(
    db: AsyncSession,
) -> list[EnterpriseIdentityConnection]:
    rows = await db.scalars(
        select(EnterpriseIdentityConnectionOrm)
        .join(
            WorkspaceOrm,
            EnterpriseIdentityConnectionOrm.workspace_id == WorkspaceOrm.id,
        )
        .where(
            EnterpriseIdentityConnectionOrm.enabled.is_(True),
            WorkspaceOrm.status == "active",
        )
        .order_by(
            EnterpriseIdentityConnectionOrm.provider,
            EnterpriseIdentityConnectionOrm.workspace_id,
        )
    )
    return [mapping.to_entity(EnterpriseIdentityConnection, row) for row in rows.all()]


async def get_connection_by_id(
    db: AsyncSession, connection_id: str, *, enabled_only: bool = False
) -> EnterpriseIdentityConnection | None:
    statement = select(EnterpriseIdentityConnectionOrm).where(
        EnterpriseIdentityConnectionOrm.id == connection_id
    )
    if enabled_only:
        statement = statement.where(EnterpriseIdentityConnectionOrm.enabled.is_(True))
    row = await db.scalar(statement)
    return mapping.to_entity(EnterpriseIdentityConnection, row) if row else None


async def lock_connection_by_id(
    db: AsyncSession, connection_id: str, *, enabled_only: bool = False
) -> EnterpriseIdentityConnection | None:
    statement = select(EnterpriseIdentityConnectionOrm).where(
        EnterpriseIdentityConnectionOrm.id == connection_id
    )
    if enabled_only:
        statement = statement.where(EnterpriseIdentityConnectionOrm.enabled.is_(True))
    row = await db.scalar(statement.with_for_update())
    return mapping.to_entity(EnterpriseIdentityConnection, row) if row else None


async def get_connection_by_provider(
    db: AsyncSession, workspace_id: str, provider: str
) -> EnterpriseIdentityConnection | None:
    row = await db.scalar(
        select(EnterpriseIdentityConnectionOrm).where(
            EnterpriseIdentityConnectionOrm.workspace_id == workspace_id,
            EnterpriseIdentityConnectionOrm.provider == provider,
        )
    )
    return mapping.to_entity(EnterpriseIdentityConnection, row) if row else None


async def get_active_workspace_name(db: AsyncSession, workspace_id: str) -> str | None:
    return await db.scalar(
        select(WorkspaceOrm.name).where(
            WorkspaceOrm.id == workspace_id,
            WorkspaceOrm.status == "active",
        )
    )


async def save_connection(
    db: AsyncSession, entity: EnterpriseIdentityConnection
) -> EnterpriseIdentityConnection:
    row = await mapping.save(db, EnterpriseIdentityConnectionOrm, entity)
    return mapping.to_entity(EnterpriseIdentityConnection, row)


async def list_identities(
    db: AsyncSession, workspace_id: str
) -> list[EnterpriseIdentity]:
    rows = await db.scalars(
        select(EnterpriseIdentityOrm)
        .join(
            EnterpriseIdentityConnectionOrm,
            EnterpriseIdentityOrm.connection_id == EnterpriseIdentityConnectionOrm.id,
        )
        .where(EnterpriseIdentityConnectionOrm.workspace_id == workspace_id)
        .order_by(EnterpriseIdentityOrm.created_at.desc())
    )
    return [mapping.to_entity(EnterpriseIdentity, row) for row in rows.all()]


async def get_identity_by_id(
    db: AsyncSession, identity_id: str
) -> EnterpriseIdentity | None:
    row = await db.get(EnterpriseIdentityOrm, identity_id)
    return mapping.to_entity(EnterpriseIdentity, row) if row else None


async def get_identity_by_subject(
    db: AsyncSession, connection_id: str, subject_id: str
) -> EnterpriseIdentity | None:
    row = await db.scalar(
        select(EnterpriseIdentityOrm).where(
            EnterpriseIdentityOrm.connection_id == connection_id,
            EnterpriseIdentityOrm.subject_id == subject_id,
        )
    )
    return mapping.to_entity(EnterpriseIdentity, row) if row else None


async def lock_identity_by_subject(
    db: AsyncSession, connection_id: str, subject_id: str
) -> EnterpriseIdentity | None:
    row = await db.scalar(
        select(EnterpriseIdentityOrm)
        .where(
            EnterpriseIdentityOrm.connection_id == connection_id,
            EnterpriseIdentityOrm.subject_id == subject_id,
        )
        .with_for_update()
    )
    return mapping.to_entity(EnterpriseIdentity, row) if row else None


async def save_identity(db: AsyncSession, entity: EnterpriseIdentity) -> EnterpriseIdentity:
    row = await mapping.save(db, EnterpriseIdentityOrm, entity)
    return mapping.to_entity(EnterpriseIdentity, row)


async def reset_identities_for_connection(db: AsyncSession, connection_id: str) -> int:
    rows = (
        await db.scalars(
            select(EnterpriseIdentityOrm).where(
                EnterpriseIdentityOrm.connection_id == connection_id
            )
        )
    ).all()
    identity_ids = [row.id for row in rows]
    if identity_ids:
        await db.execute(
            delete(RefreshSessionOrm).where(
                RefreshSessionOrm.enterprise_identity_id.in_(identity_ids)
            )
        )
    for row in rows:
        row.user_id = None
        row.status = "disabled"
    await db.flush()
    return len(rows)


async def delete_sessions_for_connection(db: AsyncSession, connection_id: str) -> None:
    identity_ids = select(EnterpriseIdentityOrm.id).where(
        EnterpriseIdentityOrm.connection_id == connection_id
    )
    await db.execute(
        delete(RefreshSessionOrm).where(
            RefreshSessionOrm.enterprise_identity_id.in_(identity_ids)
        )
    )


async def delete_expired_login_states(db: AsyncSession, now: datetime) -> None:
    await db.execute(delete(EnterpriseLoginStateOrm).where(EnterpriseLoginStateOrm.expires_at <= now))


async def save_login_state(
    db: AsyncSession, entity: EnterpriseLoginState
) -> EnterpriseLoginState:
    row = await mapping.save(db, EnterpriseLoginStateOrm, entity)
    return mapping.to_entity(EnterpriseLoginState, row)


async def lock_login_state(
    db: AsyncSession, state_hash: str
) -> EnterpriseLoginState | None:
    row = await db.scalar(
        select(EnterpriseLoginStateOrm)
        .where(EnterpriseLoginStateOrm.state_hash == state_hash)
        .with_for_update()
    )
    return mapping.to_entity(EnterpriseLoginState, row) if row else None
