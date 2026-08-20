import hashlib
import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.user import User
from app.entities.workspace import WorkspaceMembership
from app.entities.workspace_invitation import WorkspaceInvitation
from app.domain.workspace_invitation import WorkspaceInvitation as WorkspaceInvitationOrm  # noqa: F401
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.repositories import workspace as workspace_repository
from app.infrastructure.repositories import workspace_invitation as invitation_repository
from app.infrastructure.config import Settings
from app.infrastructure.security import hash_password
from app.infrastructure.validation import normalize_email, normalize_name, normalize_username
from app.infrastructure.model_utils import utc_now
from app.schemas.invitation import (
    WorkspaceInvitationAcceptRequest,
    WorkspaceInvitationCreateRequest,
    WorkspaceInvitationResponse,
)
from app.schemas.user import UserResponse
from app.application.identity import user_to_response_with_scopes
from app.application.email import (
    cancel_source_emails,
    dispatch_email_deliveries,
    queue_identity_email,
)
from app.shareddomain.audit.services import record_audit_log


def _hash_token(token: str) -> str:
    """Create a SHA-256 hexadecimal digest from an invitation token.
    
    Parameters:
    	token (str): The invitation token to hash.
    
    Returns:
    	str: The token's SHA-256 hexadecimal digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _response(
    entity: WorkspaceInvitation,
    token: str | None = None,
    email_delivery_status: str | None = None,
) -> WorkspaceInvitationResponse:
    """
    Convert a workspace invitation entity into an API response.
    
    Parameters:
        entity (WorkspaceInvitation): Invitation entity to represent.
        token (str | None): Optional raw invitation token to include in the response.
    
    Returns:
        WorkspaceInvitationResponse: Response containing the invitation details and, when provided, its token and invite URL.
    """
    return WorkspaceInvitationResponse(
        id=entity.id,
        workspace_id=entity.workspace_id,
        kind="generic" if entity.username is None else "personal",
        username=entity.username,
        email=entity.email,
        name=entity.name,
        role=entity.role,
        expires_at=entity.expires_at,
        accepted_at=entity.accepted_at,
        created_at=entity.created_at,
        token=token,
        invite_url=(
            f"/invite/{token}{'?mode=generic' if entity.username is None else ''}"
            if token
            else None
        ),
        email_delivery_status=email_delivery_status,
    )


async def create_workspace_invitation(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    payload: WorkspaceInvitationCreateRequest,
    settings: Settings,
) -> WorkspaceInvitationResponse:
    """
    Create a personal or reusable generic workspace invitation.
    
    Parameters:
        workspace_id (str): Identifier of the workspace receiving the invitation.
        actor (User): User creating the invitation.
        payload (WorkspaceInvitationCreateRequest): Invitation kind, optional recipient, and role.
    
    Returns:
        WorkspaceInvitationResponse: The created invitation, including its raw invitation token.
    """
    if payload.role == "admin" and not actor.is_global_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a system admin can invite workspace admins.")
    workspace = await workspace_repository.get_workspace_by_id(db, workspace_id)
    if workspace is None or workspace.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    token = secrets.token_urlsafe(32)
    entity = WorkspaceInvitation(
        workspace_id=workspace_id,
        username=(
            normalize_username(payload.username)
            if payload.username is not None
            else None
        ),
        email=(
            normalize_email(payload.email)
            if payload.email is not None
            else None
        ),
        name=normalize_name(payload.name) if payload.name is not None else None,
        role=payload.role,
        token_hash=_hash_token(token),
        invited_by_user_id=actor.id,
        expires_at=utc_now() + timedelta(days=7),
    )
    delivery_ids: list[str] = []
    email_delivery_status = "not_applicable"
    try:
        await invitation_repository.create(db, entity)
        if entity.email is not None and entity.name is not None:
            delivery_id = await queue_identity_email(
                db,
                settings,
                kind="workspace_invitation",
                recipient=entity.email,
                payload={
                    "name": entity.name,
                    "workspace": workspace.name,
                    "inviter": actor.name,
                    "role": entity.role,
                },
                path=f"/invite/{token}",
                expires_at=entity.expires_at,
                source_type="workspace_invitation",
                source_id=entity.id,
            )
            if delivery_id is None:
                email_delivery_status = "not_configured"
            else:
                delivery_ids.append(delivery_id)
                email_delivery_status = "queued"
        record_audit_log(
            db,
            actor,
            "workspace.invitation.create",
            "workspace_invitation",
            entity.id,
            entity.email or "Generic invitation",
            {
                "role": entity.role,
                "username": entity.username,
                "kind": payload.kind,
            },
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An invitation with this token already exists.") from exc
    await dispatch_email_deliveries(delivery_ids, settings)
    return _response(entity, token, email_delivery_status)


async def list_workspace_invitations(
    db: AsyncSession,
    workspace_id: str,
) -> list[WorkspaceInvitationResponse]:
    """
    List all invitations associated with a workspace.
    
    Parameters:
    	workspace_id (str): Identifier of the workspace whose invitations are retrieved.
    
    Returns:
    	list[WorkspaceInvitationResponse]: Invitation responses without raw invitation tokens.
    """
    return [_response(item) for item in await invitation_repository.list_for_workspace(db, workspace_id)]


async def revoke_workspace_invitation(
    db: AsyncSession,
    workspace_id: str,
    invitation_id: str,
    actor: User,
) -> None:
    """
    Revoke a workspace invitation.
    
    Parameters:
    	workspace_id (str): Identifier of the workspace containing the invitation.
    	invitation_id (str): Identifier of the invitation to revoke.
    	actor (User): User performing the revocation.
    
    Raises:
    	HTTPException: If the invitation does not exist in the workspace.
    """
    invitation = await invitation_repository.get_by_id(db, workspace_id, invitation_id)
    if invitation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
    invitation.accepted_at = utc_now()
    await invitation_repository.save(db, invitation)
    await cancel_source_emails(db, "workspace_invitation", invitation.id)
    record_audit_log(
        db,
        actor,
        "workspace.invitation.revoke",
        "workspace_invitation",
        invitation.id,
        invitation.id,
        {},
        workspace_id=workspace_id,
    )
    await db.commit()


async def delete_workspace_invitation(
    db: AsyncSession,
    workspace_id: str,
    invitation_id: str,
    actor: User,
) -> None:
    """Delete a workspace invitation and cancel its queued email."""
    invitation = await invitation_repository.get_by_id(db, workspace_id, invitation_id)
    if invitation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
    await cancel_source_emails(db, "workspace_invitation", invitation.id)
    await invitation_repository.delete(db, invitation)
    record_audit_log(
        db,
        actor,
        "workspace.invitation.delete",
        "workspace_invitation",
        invitation.id,
        invitation.id,
        {},
        workspace_id=workspace_id,
    )
    await db.commit()


async def accept_workspace_invitation(
    db: AsyncSession,
    payload: WorkspaceInvitationAcceptRequest,
    settings: Settings,
) -> UserResponse:
    """
    Accept an invitation and create the user's account and workspace membership.
    
    Parameters:
	payload (WorkspaceInvitationAcceptRequest): Token, password, and generic-invite account details.
    
    Returns:
    	UserResponse: The created user with workspace scope information.
    """
    invitation = await invitation_repository.get_by_token_hash(
        db, _hash_token(payload.token), utc_now()
    )
    if invitation is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invitation is invalid or expired.")
    is_generic = invitation.username is None
    if is_generic:
        if payload.username is None or payload.email is None or payload.name is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Generic invitations require username, email, and name.",
            )
        username = normalize_username(payload.username)
        email = normalize_email(payload.email)
        name = normalize_name(payload.name)
    else:
        username = invitation.username
        email = invitation.email
        name = invitation.name
    if username is None or email is None or name is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invitation is invalid or expired.")
    if await user_repository.find_users_by_identity(db, username, email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists.")
    workspace = await workspace_repository.get_workspace_by_id(db, invitation.workspace_id)
    if workspace is None or workspace.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    user = User(
        username=username,
        email=email,
        name=name,
        password_hash=hash_password(payload.password),
        must_change_password=False,
    )
    delivery_ids: list[str] = []
    try:
        user = await user_repository.create_user(db, user)
        await user_repository.create_workspace_membership(
            db,
            WorkspaceMembership(
                workspace_id=invitation.workspace_id,
                user_id=user.id,
                role=invitation.role,
            ),
        )
        if not is_generic:
            invitation.accepted_at = utc_now()
            await invitation_repository.save(db, invitation)
            await cancel_source_emails(
                db,
                "workspace_invitation",
                invitation.id,
            )
        inviter = await user_repository.get_user_by_id(db, invitation.invited_by_user_id)
        if inviter is not None:
            record_audit_log(
                db,
                inviter,
                "workspace.invitation.accept",
                "user",
                user.id,
                user.name,
                {
                    "invitation_id": invitation.id,
                    "kind": "generic" if is_generic else "personal",
                },
                workspace_id=invitation.workspace_id,
            )
        delivery_id = await queue_identity_email(
            db,
            settings,
            kind="welcome",
            recipient=user.email,
            payload={
                "name": user.name,
                "username": user.username,
                "workspace": workspace.name,
            },
            path="/login",
            expires_at=utc_now() + timedelta(days=7),
            user_id=user.id,
            source_type="user",
            source_id=user.id,
        )
        if delivery_id is not None:
            delivery_ids.append(delivery_id)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists.") from exc
    await dispatch_email_deliveries(delivery_ids, settings)
    return await user_to_response_with_scopes(db, user)
