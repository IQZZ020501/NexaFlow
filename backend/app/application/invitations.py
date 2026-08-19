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
from app.shareddomain.audit.services import record_audit_log


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _response(entity: WorkspaceInvitation, token: str | None = None) -> WorkspaceInvitationResponse:
    return WorkspaceInvitationResponse(
        id=entity.id,
        workspace_id=entity.workspace_id,
        username=entity.username,
        email=entity.email,
        name=entity.name,
        role=entity.role,
        expires_at=entity.expires_at,
        accepted_at=entity.accepted_at,
        created_at=entity.created_at,
        token=token,
        invite_url=f"/invite/{token}" if token else None,
    )


async def create_workspace_invitation(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    payload: WorkspaceInvitationCreateRequest,
) -> WorkspaceInvitationResponse:
    if payload.role == "admin" and not actor.is_global_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a system admin can invite workspace admins.")
    workspace = await workspace_repository.get_workspace_by_id(db, workspace_id)
    if workspace is None or workspace.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    token = secrets.token_urlsafe(32)
    entity = WorkspaceInvitation(
        workspace_id=workspace_id,
        username=normalize_username(payload.username),
        email=normalize_email(payload.email),
        name=normalize_name(payload.name),
        role=payload.role,
        token_hash=_hash_token(token),
        invited_by_user_id=actor.id,
        expires_at=utc_now() + timedelta(days=7),
    )
    try:
        await invitation_repository.create(db, entity)
        record_audit_log(
            db,
            actor,
            "workspace.invitation.create",
            "workspace_invitation",
            entity.id,
            entity.email,
            {"role": entity.role, "username": entity.username},
            workspace_id=workspace_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An invitation with this token already exists.") from exc
    return _response(entity, token)


async def list_workspace_invitations(
    db: AsyncSession,
    workspace_id: str,
) -> list[WorkspaceInvitationResponse]:
    return [_response(item) for item in await invitation_repository.list_for_workspace(db, workspace_id)]


async def revoke_workspace_invitation(
    db: AsyncSession,
    workspace_id: str,
    invitation_id: str,
    actor: User,
) -> None:
    invitation = await invitation_repository.get_by_id(db, workspace_id, invitation_id)
    if invitation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
    invitation.accepted_at = utc_now()
    await invitation_repository.save(db, invitation)
    record_audit_log(
        db,
        actor,
        "workspace.invitation.revoke",
        "workspace_invitation",
        invitation.id,
        invitation.email,
        {},
        workspace_id=workspace_id,
    )
    await db.commit()


async def accept_workspace_invitation(
    db: AsyncSession,
    payload: WorkspaceInvitationAcceptRequest,
) -> UserResponse:
    invitation = await invitation_repository.get_by_token_hash(
        db, _hash_token(payload.token), utc_now()
    )
    if invitation is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invitation is invalid or expired.")
    if await user_repository.find_users_by_identity(db, invitation.username, invitation.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists.")
    workspace = await workspace_repository.get_workspace_by_id(db, invitation.workspace_id)
    if workspace is None or workspace.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    user = User(
        username=invitation.username,
        email=invitation.email,
        name=invitation.name,
        password_hash=hash_password(payload.password),
        must_change_password=False,
    )
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
        invitation.accepted_at = utc_now()
        await invitation_repository.save(db, invitation)
        inviter = await user_repository.get_user_by_id(db, invitation.invited_by_user_id)
        if inviter is not None:
            record_audit_log(
                db,
                inviter,
                "workspace.invitation.accept",
                "user",
                user.id,
                user.name,
                {"invitation_id": invitation.id},
                workspace_id=invitation.workspace_id,
            )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists.") from exc
    return await user_to_response_with_scopes(db, user)
