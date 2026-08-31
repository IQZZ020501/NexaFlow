from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shareddomain.platform.models import Team as TeamOrm
from app.shareddomain.platform.models import TeamMembership as TeamMembershipOrm
from app.shareddomain.platform.models import RefreshSession as RefreshSessionOrm
from app.shareddomain.platform.models import User as UserOrm
from app.shareddomain.platform.models import Workspace as WorkspaceOrm
from app.shareddomain.platform.models import WorkspaceMembership as WorkspaceMembershipOrm
from app.entities.team import Team, TeamMembership
from app.entities.user import RefreshSession, User
from app.entities.workspace import WORKSPACE_ADMIN_ROLE
from app.entities.workspace import Workspace, WorkspaceMembership
from app.infrastructure.repositories import mapping
from app.infrastructure.model_utils import utc_now


async def list_users(
    db: AsyncSession,
    limit: int | None = None,
    offset: int = 0,
) -> list[User]:
    """
    List users ordered by creation time from newest to oldest.
    
    Parameters:
    	limit (int | None): Maximum number of users to return.
    	offset (int): Number of users to skip before collecting results.
    
    Returns:
    	list[User]: Users matching the pagination parameters.
    """
    result = await db.scalars(
        select(UserOrm)
        .order_by(UserOrm.created_at.desc(), UserOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [mapping.to_entity(User, row) for row in result.all()]


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    row = await db.get(UserOrm, user_id)
    return mapping.to_entity(User, row) if row is not None else None


async def lock_user(db: AsyncSession, user_id: str) -> User | None:
    row = await db.scalar(
        select(UserOrm).where(UserOrm.id == user_id).with_for_update()
    )
    return mapping.to_entity(User, row) if row is not None else None


async def list_users_by_ids(db: AsyncSession, user_ids: list[str]) -> list[User]:
    if not user_ids:
        return []
    rows = await db.scalars(select(UserOrm).where(UserOrm.id.in_(user_ids)))
    return [mapping.to_entity(User, row) for row in rows.all()]


async def get_active_user_by_username(db: AsyncSession, username: str) -> User | None:
    row = await db.scalar(
        select(UserOrm).where(
            UserOrm.username == username,
            UserOrm.is_active.is_(True),
        )
    )
    return mapping.to_entity(User, row) if row is not None else None


async def get_active_user_by_email(db: AsyncSession, email: str) -> User | None:
    row = await db.scalar(
        select(UserOrm).where(
            UserOrm.email == email,
            UserOrm.is_active.is_(True),
        )
    )
    return mapping.to_entity(User, row) if row is not None else None


async def get_active_refresh_session(
    db: AsyncSession,
    token_hash: str,
    now: datetime,
) -> RefreshSession | None:
    """
    Finds an active refresh session matching a token hash.
    
    Parameters:
    	token_hash (str): Hash of the refresh token to locate.
    	now (datetime): Reference time used to determine whether the session has expired.
    
    Returns:
    	RefreshSession | None: The matching active session, or `None` if no eligible session exists.
    """
    row = await db.scalar(
        select(RefreshSessionOrm)
        .join(UserOrm, RefreshSessionOrm.user_id == UserOrm.id)
        .where(
            RefreshSessionOrm.token_hash == token_hash,
            RefreshSessionOrm.expires_at > now,
            RefreshSessionOrm.revoked_at.is_(None),
            UserOrm.is_active.is_(True),
        )
    )
    return mapping.to_entity(RefreshSession, row) if row is not None else None


async def delete_expired_refresh_sessions(db: AsyncSession, now: datetime) -> None:
    await db.execute(
        delete(RefreshSessionOrm).where(RefreshSessionOrm.expires_at <= now)
    )


async def delete_refresh_session(db: AsyncSession, token_hash: str) -> None:
    """Delete the refresh session identified by its token hash.
    
    Parameters:
    	token_hash (str): Hash of the token associated with the session.
    """
    await db.execute(
        delete(RefreshSessionOrm).where(RefreshSessionOrm.token_hash == token_hash)
    )


async def list_refresh_sessions(
    db: AsyncSession,
    user_id: str,
    now: datetime,
) -> list[RefreshSession]:
    """
    List a user's active refresh sessions ordered by most recent use.
    
    Parameters:
    	user_id (str): Identifier of the user whose sessions are listed.
    	now (datetime): Reference time used to exclude expired sessions.
    
    Returns:
    	list[RefreshSession]: The user's unexpired, unrevoked refresh sessions.
    """
    result = await db.scalars(
        select(RefreshSessionOrm)
        .where(
            RefreshSessionOrm.user_id == user_id,
            RefreshSessionOrm.expires_at > now,
            RefreshSessionOrm.revoked_at.is_(None),
        )
        .order_by(RefreshSessionOrm.last_used_at.desc(), RefreshSessionOrm.id.desc())
    )
    return [mapping.to_entity(RefreshSession, row) for row in result.all()]


async def revoke_refresh_session_by_id(
    db: AsyncSession,
    session_id: str,
    user_id: str | None = None,
) -> None:
    """
    Revoke a refresh session by its identifier.
    
    Parameters:
    	session_id (str): Identifier of the refresh session to revoke.
    	user_id (str | None): Optional user identifier that restricts the session lookup.
    
    """
    statement = select(RefreshSessionOrm).where(RefreshSessionOrm.id == session_id)
    if user_id is not None:
        statement = statement.where(RefreshSessionOrm.user_id == user_id)
    row = await db.scalar(statement)
    if row is not None:
        row.revoked_at = utc_now()


async def delete_refresh_sessions_for_user(db: AsyncSession, user_id: str) -> None:
    """Delete all refresh sessions belonging to a user.
    
    Parameters:
    	user_id (str): Identifier of the user whose refresh sessions are deleted.
    """
    await db.execute(
        delete(RefreshSessionOrm).where(RefreshSessionOrm.user_id == user_id)
    )


async def revoke_other_refresh_sessions(
    db: AsyncSession,
    user_id: str,
    current_session_id: str | None,
    now: datetime,
) -> None:
    """
    Revoke a user's other active refresh sessions.
    
    Parameters:
    	user_id (str): Identifier of the user whose sessions should be revoked.
    	current_session_id (str | None): Identifier of the session to keep active, if provided.
    	now (datetime): Timestamp recorded as the revocation time.
    """
    statement = select(RefreshSessionOrm).where(
        RefreshSessionOrm.user_id == user_id,
        RefreshSessionOrm.revoked_at.is_(None),
        RefreshSessionOrm.expires_at > now,
    )
    if current_session_id:
        statement = statement.where(RefreshSessionOrm.id != current_session_id)
    for row in (await db.scalars(statement)).all():
        row.revoked_at = now


async def list_workspace_scope_rows(
    db: AsyncSession,
    user_ids: list[str],
):
    """
    Retrieve workspace memberships and their corresponding workspaces for the specified users.
    
    Parameters:
    	user_ids (list[str]): User identifiers whose workspace memberships should be retrieved.
    
    Returns:
    	list[tuple[WorkspaceMembership, Workspace]]: Membership and workspace entity pairs ordered by workspace creation time.
    """
    if not user_ids:
        return []

    result = await db.execute(
        select(WorkspaceMembershipOrm, WorkspaceOrm)
        .join(WorkspaceOrm, WorkspaceMembershipOrm.workspace_id == WorkspaceOrm.id)
        .where(WorkspaceMembershipOrm.user_id.in_(user_ids))
        .order_by(WorkspaceOrm.created_at)
    )
    return [
        (
            mapping.to_entity(WorkspaceMembership, membership),
            mapping.to_entity(Workspace, workspace),
        )
        for membership, workspace in result.all()
    ]


async def list_team_scope_rows(
    db: AsyncSession,
    user_ids: list[str],
):
    if not user_ids:
        return []

    result = await db.execute(
        select(TeamMembershipOrm, TeamOrm)
        .join(TeamOrm, TeamMembershipOrm.team_id == TeamOrm.id)
        .where(TeamMembershipOrm.user_id.in_(user_ids))
        .order_by(TeamOrm.created_at)
    )
    return [
        (
            mapping.to_entity(TeamMembership, membership),
            mapping.to_entity(Team, team),
        )
        for membership, team in result.all()
    ]


async def list_admin_workspace_ids_for_user(
    db: AsyncSession,
    user_id: str,
) -> list[str]:
    result = await db.scalars(
        select(WorkspaceMembershipOrm.workspace_id).where(
            WorkspaceMembershipOrm.user_id == user_id,
            WorkspaceMembershipOrm.role == WORKSPACE_ADMIN_ROLE,
        )
    )
    return list(result.all())


async def active_admin_counts_by_workspace(
    db: AsyncSession,
    workspace_ids: list[str],
) -> dict[str, int]:
    result = await db.execute(
        select(WorkspaceMembershipOrm.workspace_id, func.count())
        .join(UserOrm, WorkspaceMembershipOrm.user_id == UserOrm.id)
        .where(
            WorkspaceMembershipOrm.workspace_id.in_(workspace_ids),
            WorkspaceMembershipOrm.role == WORKSPACE_ADMIN_ROLE,
            UserOrm.is_active.is_(True),
        )
        .group_by(WorkspaceMembershipOrm.workspace_id)
    )
    return dict(result.all())


async def list_workspace_memberships_for_user(
    db: AsyncSession,
    user_id: str,
) -> list[WorkspaceMembership]:
    result = await db.scalars(
        select(WorkspaceMembershipOrm).where(
            WorkspaceMembershipOrm.user_id == user_id
        )
    )
    return [
        mapping.to_entity(WorkspaceMembership, row) for row in result.all()
    ]


async def find_users_by_identity(
    db: AsyncSession,
    username: str,
    email: str,
) -> list[User]:
    result = await db.scalars(
        select(UserOrm).where(
            or_(UserOrm.username == username, UserOrm.email == email)
        )
    )
    return [mapping.to_entity(User, row) for row in result.all()]


async def delete_user_graph(db: AsyncSession, user_id: str) -> None:
    await delete_refresh_sessions_for_user(db, user_id)
    await db.execute(delete(TeamMembershipOrm).where(TeamMembershipOrm.user_id == user_id))
    await db.execute(
        delete(WorkspaceMembershipOrm).where(WorkspaceMembershipOrm.user_id == user_id)
    )
    await db.execute(delete(UserOrm).where(UserOrm.id == user_id))


async def create_user(db: AsyncSession, entity: User) -> User:
    orm_row = await mapping.save(db, UserOrm, entity)
    return mapping.to_entity(User, orm_row)


async def create_refresh_session(
    db: AsyncSession,
    entity: RefreshSession,
) -> RefreshSession:
    """Persist a refresh session and return the resulting domain entity.
    
    Parameters:
    	entity (RefreshSession): The refresh session to persist.
    
    Returns:
    	RefreshSession: The persisted refresh session.
    """
    orm_row = await mapping.save(db, RefreshSessionOrm, entity)
    return mapping.to_entity(RefreshSession, orm_row)


async def save_refresh_session(
    db: AsyncSession,
    entity: RefreshSession,
) -> RefreshSession:
    """Persist an existing refresh session and return its domain entity.
    
    Parameters:
    	entity (RefreshSession): The refresh session to save.
    
    Returns:
    	RefreshSession: The saved refresh session.
    """
    orm_row = await mapping.save(db, RefreshSessionOrm, entity)
    return mapping.to_entity(RefreshSession, orm_row)


async def create_workspace_membership(
    db: AsyncSession,
    entity: WorkspaceMembership,
) -> WorkspaceMembership:
    """
    Create and persist a workspace membership.
    
    Parameters:
    	entity (WorkspaceMembership): The workspace membership to persist.
    
    Returns:
    	WorkspaceMembership: The persisted workspace membership.
    """
    orm_row = await mapping.save(db, WorkspaceMembershipOrm, entity)
    return mapping.to_entity(WorkspaceMembership, orm_row)


async def create_team_membership(
    db: AsyncSession,
    entity: TeamMembership,
) -> TeamMembership:
    orm_row = await mapping.save(db, TeamMembershipOrm, entity)
    return mapping.to_entity(TeamMembership, orm_row)


async def save_user(db: AsyncSession, entity: User) -> User:
    orm_row = await mapping.save(db, UserOrm, entity)
    return mapping.to_entity(User, orm_row)


async def refresh_user(db: AsyncSession, entity: User) -> User:
    return await mapping.refresh_entity(db, UserOrm, User, entity)
