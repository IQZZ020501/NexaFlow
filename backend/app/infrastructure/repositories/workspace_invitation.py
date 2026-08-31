from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shareddomain.platform.models import WorkspaceInvitation as InvitationOrm
from app.entities.workspace_invitation import WorkspaceInvitation
from app.infrastructure.repositories import mapping


async def create(
    db: AsyncSession,
    entity: WorkspaceInvitation,
) -> WorkspaceInvitation:
    """
    Persist a workspace invitation and return its domain entity.
    
    Parameters:
    	entity (WorkspaceInvitation): The invitation to persist.
    
    Returns:
    	WorkspaceInvitation: The persisted workspace invitation.
    """
    row = await mapping.save(db, InvitationOrm, entity)
    return mapping.to_entity(WorkspaceInvitation, row)


async def get_by_token_hash(
    db: AsyncSession,
    token_hash: str,
    now: datetime,
) -> WorkspaceInvitation | None:
    """
    Find an active workspace invitation by its token hash.
    
    Parameters:
    	token_hash (str): Hash of the invitation token to match
    	now (datetime): Reference time used to determine whether the invitation has expired
    
    Returns:
        WorkspaceInvitation | None: The matching active, unexpired invitation, or `None` if no match exists.
    """
    # ponytail: one row lock per link; split generic lookups if signup contention is measured.
    row = await db.scalar(
        select(InvitationOrm).where(
            InvitationOrm.token_hash == token_hash,
            InvitationOrm.accepted_at.is_(None),
            InvitationOrm.expires_at > now,
        ).with_for_update()
    )
    return mapping.to_entity(WorkspaceInvitation, row) if row is not None else None


async def get_by_id(
    db: AsyncSession,
    workspace_id: str,
    invitation_id: str,
) -> WorkspaceInvitation | None:
    """
    Retrieve a workspace invitation by its identifier.
    
    Parameters:
    	workspace_id (str): Identifier of the workspace containing the invitation.
    	invitation_id (str): Identifier of the invitation to retrieve.
    
    Returns:
    	WorkspaceInvitation | None: The matching invitation, or `None` if it does not exist in the workspace.
    """
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
    """Retrieve all invitations for a workspace, ordered by creation time and ID from newest to oldest.
    
    Parameters:
    	workspace_id (str): The workspace whose invitations to retrieve.
    
    Returns:
    	list[WorkspaceInvitation]: The workspace's invitations in descending creation and ID order.
    """
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
    """Persist or update a workspace invitation.
    
    Parameters:
    	entity (WorkspaceInvitation): The invitation to save.
    
    Returns:
    	WorkspaceInvitation: The persisted workspace invitation.
    """
    row = await mapping.save(db, InvitationOrm, entity)
    return mapping.to_entity(WorkspaceInvitation, row)


async def delete(
    db: AsyncSession,
    entity: WorkspaceInvitation,
) -> None:
    """Delete a workspace invitation."""
    row = await db.get(InvitationOrm, entity.id)
    if row is not None:
        await db.delete(row)
        await db.flush()
