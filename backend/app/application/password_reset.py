"""Anonymous password-reset request and confirmation use cases."""

import hashlib
import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.email import (
    dispatch_email_deliveries,
    identity_email_is_ready,
    queue_identity_email,
)
from app.entities.email import PasswordResetToken
from app.infrastructure.agent_rate_limit import (
    PasswordResetRateLimitExceeded,
    PasswordResetRateLimitUnavailable,
    enforce_password_reset_rate_limit,
)
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import email as email_repository
from app.infrastructure.repositories import user as user_repository
from app.infrastructure.security import hash_password, verify_password
from app.infrastructure.system_log import record_system_log
from app.infrastructure.validation import normalize_email
from app.shareddomain.audit.services import record_audit_log

RESET_EXPIRES_MINUTES = 30
RESET_INVALID_DETAIL = "Password reset link is invalid or expired."


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def request_password_reset(
    db: AsyncSession,
    email: str,
    settings: Settings,
    source_ip: str | None,
) -> None:
    if not await identity_email_is_ready(db):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Email service is not configured.",
        )
    normalized_email = normalize_email(email)
    try:
        await enforce_password_reset_rate_limit(
            settings,
            normalized_email,
            source_ip,
        )
    except PasswordResetRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many password reset requests.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except PasswordResetRateLimitUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Password reset is temporarily unavailable.",
        ) from exc

    user = await user_repository.get_active_user_by_email(db, normalized_email)
    delivery_ids: list[str] = []
    if user is not None:
        user = await user_repository.lock_user(db, user.id)
    if user is not None and user.is_active and user.email == normalized_email:
        now = utc_now()
        expires_at = now + timedelta(minutes=RESET_EXPIRES_MINUTES)
        await email_repository.delete_expired_password_reset_tokens(db, now)
        await email_repository.invalidate_password_reset_tokens(db, user.id, now)
        await email_repository.delete_password_reset_deliveries(db, user.id)
        raw_token = secrets.token_urlsafe(48)
        await email_repository.create_password_reset_token(
            db,
            PasswordResetToken(
                user_id=user.id,
                token_hash=_token_hash(raw_token),
                expires_at=expires_at,
            ),
        )
        delivery_id = await queue_identity_email(
            db,
            settings,
            kind="password_reset",
            recipient=user.email,
            payload={"name": user.name},
            path=f"/reset-password/{raw_token}",
            expires_at=expires_at,
            user_id=user.id,
            source_type="password_reset",
            source_id=user.id,
        )
        if delivery_id is None:
            await db.rollback()
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Email service is not configured.",
            )
        delivery_ids.append(delivery_id)

    record_system_log(
        db,
        level="info",
        event="auth.password_reset_requested",
        message="Password reset request accepted.",
        path="/api/v1/auth/password-reset/request",
        method="POST",
        status_code=status.HTTP_202_ACCEPTED,
        ip_address=source_ip,
    )
    await db.commit()
    await dispatch_email_deliveries(delivery_ids, settings)


async def confirm_password_reset(
    db: AsyncSession,
    token: str,
    new_password: str,
    settings: Settings,
) -> None:
    token_hash = _token_hash(token)
    user_id = await email_repository.get_password_reset_token_user_id(db, token_hash)
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, RESET_INVALID_DETAIL)
    user = await user_repository.lock_user(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, RESET_INVALID_DETAIL)
    now = utc_now()
    reset_token = await email_repository.lock_active_password_reset_token(
        db,
        token_hash,
        now,
    )
    if reset_token is None or reset_token.user_id != user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, RESET_INVALID_DETAIL)
    if verify_password(new_password, user.password_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "New password must be different.",
        )

    reset_token.used_at = now
    await email_repository.save_password_reset_token(db, reset_token)
    await email_repository.invalidate_password_reset_tokens(db, user.id, now)
    await email_repository.delete_password_reset_deliveries(db, user.id)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    await user_repository.delete_refresh_sessions_for_user(db, user.id)
    user = await user_repository.save_user(db, user)
    delivery_id = await queue_identity_email(
        db,
        settings,
        kind="password_changed",
        recipient=user.email,
        payload={
            "name": user.name,
            "changed_by": "password reset",
            "changed_at": now.isoformat(),
        },
        expires_at=now + timedelta(days=7),
        user_id=user.id,
        source_type="user",
        source_id=user.id,
    )
    record_audit_log(
        db,
        user,
        "user.password_reset",
        "user",
        user.id,
        user.name,
        {"sessions_revoked": True},
    )
    await db.commit()
    await dispatch_email_deliveries(
        [delivery_id] if delivery_id is not None else [],
        settings,
    )
