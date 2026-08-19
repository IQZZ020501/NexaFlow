from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.workspace_invitation import WorkspaceInvitation as InvitationOrm
from app.entities.workspace_invitation import WorkspaceInvitation
from app.infrastructure.repositories import mapping


async def create(
    db: AsyncSession,
    entity: WorkspaceInvitation,
) -> WorkspaceInvitation:
    row = await mapping.save(db, InvitationOrm, entity)
    return mapping.to_entity(WorkspaceInvitation, row)


async def get_by_token_hash(
    db: AsyncSession,
    token_hash: str,
    now: datetime,
) -> WorkspaceInvitation | None:
    row = await db.scalar(
        select(InvitationOrm).where(
            InvitationOrm.token_hash == token_hash,
            InvitationOrm.accepted_at.is_(None),
            InvitationOrm.expires_at > now,
        )
    )
    return mapping.to_entity(WorkspaceInvitation, row) if row is not None else None


async def get_by_id(
    db: AsyncSession,
    workspace_id: str,
    invitation_id: str,
) -> WorkspaceInvitation | None:
    row = await db.scalar(
        select(InvitationOrm).where(
            InvitationOrm.id == invitation_id,
            InvitationOrm.workspace_id == workspace_id,
        )
    )
    return mapping.to_entity(WorkspaceInvitation, row) if row is not None else None


async def list_for_workspace(
    db: AsyncSession,
    workspace_id: str,
) -> list[WorkspaceInvitation]:
    result = await db.scalars(
        select(InvitationOrm)
        .where(InvitationOrm.workspace_id == workspace_id)
        .order_by(InvitationOrm.created_at.desc(), InvitationOrm.id.desc())
    )
    return [mapping.to_entity(WorkspaceInvitation, row) for row in result.all()]


async def save(
    db: AsyncSession,
    entity: WorkspaceInvitation,
) -> WorkspaceInvitation:
    row = await mapping.save(db, InvitationOrm, entity)
    return mapping.to_entity(WorkspaceInvitation, row)
