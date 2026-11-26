"""Audited local operator recovery for a locked-out account.

Default mode is read-only. Pass ``--user-id <id> --apply`` to issue a one-time
24-hour temporary password for an active account identified by its immutable
user ID, revoke its existing refresh sessions and password-reset tokens, and
record durable audit and system logs. Never alters roles or account status and
never reads recovery triggers or passwords from environment variables.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit.services import record_audit_log
from app.domain.platform.models import User as UserOrm
from app.entities.defaults import utc_now
from app.entities.identity.user import User
from app.infra.config.settings import Settings
from app.infra.db import mapping
from app.infra.db.repositories.email import delivery as email_repository
from app.infra.db.repositories.identity import users as user_repository
from app.infra.db.session import configure_database, get_engine, get_session_factory
from app.infra.observability.system_log import record_system_log
from app.infra.security.auth import hash_password

LOCAL_OPERATOR_ACTOR_ID = "local-operator"
LOCAL_OPERATOR_ACTOR_NAME = "Local Operator Recovery"


@dataclass(frozen=True)
class RecoveryResult:
    user: User
    temporary_password: str
    expires_at_iso: str


async def list_global_admins(db: AsyncSession) -> list[User]:
    rows = await db.scalars(
        select(UserOrm)
        .where(UserOrm.is_global_admin.is_(True))
        .order_by(UserOrm.created_at.asc(), UserOrm.id.asc())
    )
    return [mapping.to_entity(User, row) for row in rows.all()]


async def inspect_user(db: AsyncSession, user_id: str) -> User:
    user = await user_repository.get_user_by_id(db, user_id)
    if user is None:
        raise ValueError("User not found.")
    return user


async def recover_user_password(
    db: AsyncSession,
    user_id: str,
    *,
    operator: str = "",
    reason: str = "",
) -> RecoveryResult:
    user = await user_repository.lock_user(db, user_id)
    if user is None:
        raise ValueError("User not found.")
    if not user.is_active:
        raise ValueError("Cannot recover an inactive user account.")

    now = utc_now()
    expires_at = now + timedelta(hours=24)
    temporary_password = f"Nxf!{secrets.token_urlsafe(18)}A1"
    operator_label = (operator.strip() or LOCAL_OPERATOR_ACTOR_ID)[:80]
    reason_text = (reason.strip() or "local operator recovery")[:200]

    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    user.initial_password_expires_at = expires_at
    await user_repository.delete_refresh_sessions_for_user(db, user.id)
    await email_repository.invalidate_password_reset_tokens(db, user.id, now)
    await email_repository.delete_password_reset_deliveries(db, user.id)
    user = await user_repository.save_user(db, user)

    actor = User(
        id=LOCAL_OPERATOR_ACTOR_ID,
        username=operator_label,
        email="local-operator@localhost",
        name=LOCAL_OPERATOR_ACTOR_NAME,
        password_hash="",
        is_global_admin=False,
        must_change_password=False,
    )
    record_audit_log(
        db,
        actor,
        "user.recover_password",
        "user",
        user.id,
        user.name,
        {
            "operator": operator_label,
            "reason": reason_text,
            "sessions_revoked": True,
            "must_change_password": True,
            "initial_password_expires_at": expires_at.isoformat(),
        },
    )
    record_system_log(
        db,
        level="warning",
        event="auth.local_password_recovery",
        message="Local operator issued a temporary recovery password.",
        user_id=user.id,
        username=user.username,
        details={
            "operator": operator_label,
            "reason": reason_text,
            "sessions_revoked": True,
            "must_change_password": True,
            "initial_password_expires_at": expires_at.isoformat(),
        },
    )
    await db.commit()
    return RecoveryResult(
        user=user,
        temporary_password=temporary_password,
        expires_at_iso=expires_at.isoformat(),
    )


def _format_user(user: User) -> str:
    expires = (
        user.initial_password_expires_at.isoformat()
        if user.initial_password_expires_at is not None
        else "none"
    )
    return (
        f"user_id={user.id} username={user.username} email={user.email} "
        f"is_global_admin={user.is_global_admin} is_active={user.is_active} "
        f"must_change_password={user.must_change_password} "
        f"initial_password_expires_at={expires}"
    )


async def run(args: argparse.Namespace) -> int:
    configure_database(Settings.from_env(require_bootstrap=False))
    try:
        async with get_session_factory()() as db:
            if args.list_admins:
                admins = await list_global_admins(db)
                if not admins:
                    print("No global admin accounts found.")
                for admin in admins:
                    print(_format_user(admin))
                return 0
            if not args.apply:
                user = await inspect_user(db, args.user_id)
                print(_format_user(user))
                return 0
            operator = args.operator or getpass.getuser() or LOCAL_OPERATOR_ACTOR_ID
            result = await recover_user_password(
                db,
                args.user_id,
                operator=operator,
                reason=args.reason,
            )
            print(_format_user(result.user))
            print(
                f"temporary_password={result.temporary_password} "
                f"expires_at={result.expires_at_iso}"
            )
            print(
                "Sign in within 24 hours and change the password immediately. "
                "All existing refresh sessions were revoked."
            )
            return 0
    finally:
        await get_engine().dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--list-admins",
        action="store_true",
        help="List global admin accounts (read-only) to locate an immutable user_id.",
    )
    target.add_argument(
        "--user-id",
        help="Immutable user ID to inspect or recover.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Issue a one-time 24h temporary password and revoke sessions for --user-id.",
    )
    parser.add_argument(
        "--operator",
        default="",
        help="Operator label recorded in audit logs (defaults to current OS user).",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Operational reason recorded in audit and system logs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.apply and not args.user_id:
        parser.error("--apply requires --user-id.")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
