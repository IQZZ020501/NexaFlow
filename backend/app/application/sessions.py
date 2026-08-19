from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.user import User
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.security import hash_refresh_token
from app.schemas.user import RefreshSessionResponse


async def list_user_sessions(
    db: AsyncSession,
    user: User,
    refresh_token: str | None = None,
) -> list[RefreshSessionResponse]:
    current_hash = hash_refresh_token(refresh_token) if refresh_token else None
    sessions = await user_repository.list_refresh_sessions(db, user.id, utc_now())
    return [
        RefreshSessionResponse(
            id=session.id,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            expires_at=session.expires_at,
            user_agent=session.user_agent,
            ip_address=session.ip_address,
            is_current=current_hash == session.token_hash,
        )
        for session in sessions
    ]


async def revoke_user_session(
    db: AsyncSession,
    user_id: str,
    session_id: str,
) -> None:
    await user_repository.revoke_refresh_session_by_id(db, session_id, user_id)
    await db.commit()


async def revoke_all_user_sessions(
    db: AsyncSession,
    user_id: str,
) -> None:
    await user_repository.delete_refresh_sessions_for_user(db, user_id)
    await db.commit()


async def revoke_other_user_sessions(
    db: AsyncSession,
    user: User,
    refresh_token: str | None,
) -> None:
    current_session_id = None
    if refresh_token:
        current = await user_repository.get_active_refresh_session(
            db, hash_refresh_token(refresh_token), utc_now()
        )
        current_session_id = current.id if current else None
    await user_repository.revoke_other_refresh_sessions(
        db, user.id, current_session_id, utc_now()
    )
    await db.commit()
