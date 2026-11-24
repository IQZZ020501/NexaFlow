"""Verify bootstrap fencing, upgrade credential retirement, and local recovery."""

import asyncio
import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tests.support import (
    ADMIN_PASSWORD,
    BOOTSTRAP_ADMIN_PASSWORD,
    _PermissiveRateLimitRedis,
)
from tests.support import (
    settings as testing_settings,
)

from app.application.identity.service import authenticate_user, change_password
from app.domain.audit.models import AuditLog as AuditLogOrm
from app.domain.email.models import EmailDelivery as EmailDeliveryOrm
from app.domain.email.models import PasswordResetToken as PasswordResetTokenOrm
from app.domain.platform.models import BootstrapState
from app.domain.platform.models import RefreshSession as RefreshSessionOrm
from app.domain.platform.models import User as UserOrm
from app.entities.defaults import utc_now
from app.entities.identity.user import User
from app.infra.bootstrap.seed import seed_bootstrap_admin
from app.infra.db.base import Base
from app.infra.db.repositories.identity import users as user_repository
from app.infra.observability.system_log import SystemLog as SystemLogOrm
from app.infra.security.auth import hash_password, verify_password
from scripts import recover_user_password as recovery


def _load_migration():
    path = Path(__file__).parents[2] / "alembic/versions/202611240001_identity_bootstrap.py"
    spec = importlib.util.spec_from_file_location("bootstrap_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


class BootstrapMigrationTests(unittest.TestCase):
    def test_existing_and_new_installations(self) -> None:
        migration = _load_migration()
        engine = sa.create_engine("sqlite://")
        with (
            engine.begin() as db,
            patch.object(migration, "op", Operations(MigrationContext.configure(db))),
        ):
            db.exec_driver_sql(
                "CREATE TABLE users("
                "id TEXT, must_change_password BOOLEAN, password_hash TEXT, is_global_admin BOOLEAN"
                ")"
            )
            db.exec_driver_sql(
                "CREATE TABLE audit_logs(action TEXT, resource_type TEXT, resource_id TEXT)"
            )
            db.exec_driver_sql("CREATE TABLE refresh_sessions(user_id TEXT)")
            migration.upgrade()
            self.assertIsNone(db.scalar(sa.text("SELECT id FROM bootstrap_state")))
            migration.downgrade()

            hasher = PasswordHash.recommended()
            default_compose_hash = hasher.hash("CHANGE_ME_Admin_123!")
            default_env_hash = hasher.hash("NexaFlow@123..")
            active_default_hash = hasher.hash("NexaFlow@123..")
            operator_hash = hasher.hash("Operator@Custom123!")

            db.execute(
                sa.text(
                    "INSERT INTO users VALUES "
                    "('pending-managed', true, 'old-managed', false),"
                    "('active-managed', false, :active_pw, false),"
                    "('bootstrap-custom', true, :operator_pw, true),"
                    "('bootstrap-compose', true, :compose_pw, true),"
                    "('bootstrap-env', true, :env_pw, true)"
                ),
                {
                    "active_pw": active_default_hash,
                    "operator_pw": operator_hash,
                    "compose_pw": default_compose_hash,
                    "env_pw": default_env_hash,
                },
            )
            db.exec_driver_sql(
                "INSERT INTO audit_logs VALUES "
                "('user.create', 'user', 'pending-managed'),"
                "('user.create', 'user', 'active-managed')"
            )
            db.exec_driver_sql(
                "INSERT INTO refresh_sessions VALUES "
                "('pending-managed'), ('active-managed'), ('bootstrap-custom'),"
                "('bootstrap-compose'), ('bootstrap-env')"
            )

            migration.upgrade()
            self.assertEqual(db.scalar(sa.text("SELECT id FROM bootstrap_state")), 1)
            rows = {
                row[0]: (row[1], bool(row[2]))
                for row in db.execute(
                    sa.text("SELECT id, password_hash, is_global_admin FROM users")
                ).all()
            }
            # Pending managed and both known default bootstrap accounts are retired.
            self.assertTrue(rows["pending-managed"][0].startswith("$argon2"))
            self.assertNotEqual(rows["pending-managed"][0], "old-managed")
            self.assertNotEqual(rows["bootstrap-compose"][0], default_compose_hash)
            self.assertFalse(hasher.verify("CHANGE_ME_Admin_123!", rows["bootstrap-compose"][0]))
            self.assertNotEqual(rows["bootstrap-env"][0], default_env_hash)
            self.assertFalse(hasher.verify("NexaFlow@123..", rows["bootstrap-env"][0]))
            # Active users and operator-chosen bootstrap credentials are untouched.
            self.assertEqual(rows["active-managed"][0], active_default_hash)
            self.assertEqual(rows["bootstrap-custom"][0], operator_hash)
            # Roles are never altered by the migration.
            self.assertFalse(rows["pending-managed"][1])
            self.assertFalse(rows["active-managed"][1])
            self.assertTrue(rows["bootstrap-custom"][1])
            self.assertTrue(rows["bootstrap-compose"][1])
            self.assertTrue(rows["bootstrap-env"][1])
            # Only retired accounts lose their refresh sessions.
            self.assertEqual(
                set(db.scalars(sa.text("SELECT user_id FROM refresh_sessions"))),
                {"active-managed", "bootstrap-custom"},
            )
            # Downgrade followed by re-upgrade preserves active users and fence.
            migration.downgrade()
            migration.upgrade()
            self.assertEqual(db.scalar(sa.text("SELECT id FROM bootstrap_state")), 1)
            self.assertEqual(
                db.scalar(sa.text("SELECT password_hash FROM users WHERE id = 'active-managed'")),
                active_default_hash,
            )

    def test_bootstrap_fencing_and_transaction_retry(self) -> None:
        async def scenario() -> None:
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                runtime_settings = testing_settings()

                # 1. Transaction failure before commit rolls back bootstrap_state so retry succeeds.
                async with factory() as db:
                    with patch(
                        "app.infra.bootstrap.seed.user_repository.create_user",
                        side_effect=RuntimeError("simulated db failure"),
                    ):
                        with self.assertRaises(RuntimeError):
                            await seed_bootstrap_admin(db, runtime_settings)
                    self.assertIsNone(await db.get(BootstrapState, 1))
                    await seed_bootstrap_admin(db, runtime_settings)
                    self.assertIsNotNone(await db.get(BootstrapState, 1))
                    users = await user_repository.list_users(db)
                    self.assertEqual(len(users), 1)
                    admin = users[0]
                    self.assertEqual(admin.username, "admin")
                    self.assertTrue(admin.is_global_admin)

                # 2. Demoting the bootstrap admin survives restart (no re-promotion).
                async with factory() as db:
                    row = await db.get(UserOrm, admin.id)
                    assert row is not None
                    row.is_global_admin = False
                    await db.commit()
                    await seed_bootstrap_admin(db, runtime_settings)
                    await db.refresh(row)
                    self.assertFalse(row.is_global_admin)

                # 3. Renaming the bootstrap admin never recreates an "admin" account on restart.
                async with factory() as db:
                    row = await db.get(UserOrm, admin.id)
                    assert row is not None
                    row.username = "renamed-founder"
                    await db.commit()
                    await seed_bootstrap_admin(db, runtime_settings)
                    usernames = set(await db.scalars(select(UserOrm.username)))
                    self.assertEqual(usernames, {"renamed-founder"})

                # 4. Deleting the bootstrap admin and reusing username "admin" for a regular user
                #    never promotes that user on restart.
                async with factory() as db:
                    await db.execute(sa.delete(UserOrm).where(UserOrm.id == admin.id))
                    reused = await user_repository.create_user(
                        db,
                        User(
                            username="admin",
                            email="regular@example.com",
                            name="Regular User",
                            password_hash=hash_password(ADMIN_PASSWORD),
                            is_global_admin=False,
                            must_change_password=False,
                        ),
                    )
                    await db.commit()
                    await seed_bootstrap_admin(db, runtime_settings)
                    reloaded = await user_repository.get_user_by_id(db, reused.id)
                    assert reloaded is not None
                    self.assertFalse(reloaded.is_global_admin)

                # 5. Even deleting every user leaves bootstrap_state fenced.
                async with factory() as db:
                    await db.execute(sa.delete(UserOrm))
                    await db.commit()
                    await seed_bootstrap_admin(
                        db, replace(runtime_settings, bootstrap_admin_username="other-admin")
                    )
                    self.assertEqual(await user_repository.list_users(db), [])
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    def test_audited_local_operator_recovery(self) -> None:
        async def scenario() -> None:
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                runtime_settings = testing_settings()
                now = utc_now()

                async with factory() as db:
                    admin = await user_repository.create_user(
                        db,
                        User(
                            username="admin",
                            email="admin@example.com",
                            name="System Admin",
                            password_hash=hash_password("Retired@Secret123"),
                            is_global_admin=True,
                            must_change_password=True,
                            is_active=True,
                        ),
                    )
                    member = await user_repository.create_user(
                        db,
                        User(
                            username="member",
                            email="member@example.com",
                            name="Regular Member",
                            password_hash=hash_password("OldMember@123"),
                            is_global_admin=False,
                            must_change_password=False,
                            is_active=True,
                        ),
                    )
                    inactive = await user_repository.create_user(
                        db,
                        User(
                            username="disabled",
                            email="disabled@example.com",
                            name="Disabled User",
                            password_hash=hash_password("Disabled@123"),
                            is_global_admin=True,
                            must_change_password=False,
                            is_active=False,
                        ),
                    )
                    db.add(
                        RefreshSessionOrm(
                            user_id=admin.id,
                            token_hash="stale-session-hash",
                            expires_at=now + timedelta(days=7),
                            last_used_at=now,
                        )
                    )
                    db.add(
                        PasswordResetTokenOrm(
                            user_id=admin.id,
                            token_hash="stale-reset-hash",
                            expires_at=now + timedelta(minutes=30),
                        )
                    )
                    db.add(
                        EmailDeliveryOrm(
                            kind="password_reset",
                            payload_ciphertext="encrypted",
                            status="pending",
                            user_id=admin.id,
                            source_type="user",
                            source_id=admin.id,
                            next_attempt_at=now,
                            expires_at=now + timedelta(hours=1),
                        )
                    )
                    await db.commit()

                # Read-only helpers list admins and inspect without modifying credentials.
                async with factory() as db:
                    admins = await recovery.list_global_admins(db)
                    self.assertEqual({item.id for item in admins}, {admin.id, inactive.id})
                    inspected = await recovery.inspect_user(db, admin.id)
                    self.assertEqual(inspected.id, admin.id)
                    self.assertTrue(verify_password("Retired@Secret123", inspected.password_hash))

                # Recovery rejects unknown and inactive users without changing anything.
                async with factory() as db:
                    with self.assertRaisesRegex(ValueError, "not found"):
                        await recovery.recover_user_password(db, "missing-user-id")
                    with self.assertRaisesRegex(ValueError, "inactive"):
                        await recovery.recover_user_password(db, inactive.id)

                # Recovering a non-admin never elevates is_global_admin.
                async with factory() as db:
                    member_res = await recovery.recover_user_password(
                        db, member.id, operator="ops-oncall", reason="member lockout"
                    )
                    self.assertFalse(member_res.user.is_global_admin)
                    self.assertTrue(member_res.user.must_change_password)

                # Recovering the locked-out admin by immutable ID issues a 24h temp password,
                # revokes sessions/reset artifacts, and writes audit & system logs without secret.
                async with factory() as db:
                    result = await recovery.recover_user_password(
                        db,
                        admin.id,
                        operator="ops-admin",
                        reason="upgrade without SMTP",
                    )
                    self.assertEqual(result.user.id, admin.id)
                    self.assertTrue(result.user.is_global_admin)
                    self.assertTrue(result.user.must_change_password)
                    self.assertIsNotNone(result.user.initial_password_expires_at)
                    self.assertTrue(
                        verify_password(result.temporary_password, result.user.password_hash)
                    )
                    self.assertFalse(
                        verify_password("Retired@Secret123", result.user.password_hash)
                    )
                    self.assertEqual(
                        list(
                            await db.scalars(
                                select(RefreshSessionOrm).where(
                                    RefreshSessionOrm.user_id == admin.id
                                )
                            )
                        ),
                        [],
                    )
                    reset_token = await db.scalar(
                        select(PasswordResetTokenOrm).where(
                            PasswordResetTokenOrm.user_id == admin.id
                        )
                    )
                    assert reset_token is not None
                    self.assertIsNotNone(reset_token.used_at)
                    self.assertEqual(
                        list(
                            await db.scalars(
                                select(EmailDeliveryOrm).where(
                                    EmailDeliveryOrm.user_id == admin.id
                                )
                            )
                        ),
                        [],
                    )
                    audit = await db.scalar(
                        select(AuditLogOrm).where(
                            AuditLogOrm.action == "user.recover_password",
                            AuditLogOrm.resource_id == admin.id,
                        )
                    )
                    assert audit is not None
                    self.assertEqual(audit.actor_user_id, recovery.LOCAL_OPERATOR_ACTOR_ID)
                    self.assertEqual(audit.actor_username, "ops-admin")
                    self.assertEqual(audit.details["reason"], "upgrade without SMTP")
                    self.assertNotIn(result.temporary_password, str(audit.details))

                    syslog = await db.scalar(
                        select(SystemLogOrm).where(
                            SystemLogOrm.event == "auth.local_password_recovery",
                            SystemLogOrm.user_id == admin.id,
                        )
                    )
                    assert syslog is not None
                    self.assertNotIn(result.temporary_password, syslog.message)
                    self.assertNotIn(result.temporary_password, str(syslog.details))

                # End-to-end: recovered temp password expires after 24h, works before expiry,
                # and forced change_password clears expiry and must_change_password.
                with patch(
                    "app.infra.security.agent_rate_limit._rate_limit_redis",
                    return_value=_PermissiveRateLimitRedis(),
                ):
                    async with factory() as db:
                        with patch(
                            "app.application.identity.service.utc_now",
                            return_value=utc_now() + timedelta(hours=25),
                        ):
                            with self.assertRaises(Exception) as expired_exc:
                                await authenticate_user(
                                    db, "admin", result.temporary_password, runtime_settings
                                )
                            self.assertEqual(getattr(expired_exc.exception, "status_code", None), 401)

                    async with factory() as db:
                        token_resp, _ = await authenticate_user(
                            db, "admin", result.temporary_password, runtime_settings
                        )
                        self.assertTrue(token_resp.must_change_password)
                        loaded = await user_repository.get_user_by_id(db, admin.id)
                        assert loaded is not None
                        await change_password(
                            db,
                            loaded,
                            BOOTSTRAP_ADMIN_PASSWORD,
                            runtime_settings,
                            current_password=result.temporary_password,
                        )
                        activated = await user_repository.get_user_by_id(db, admin.id)
                        assert activated is not None
                        self.assertFalse(activated.must_change_password)
                        self.assertIsNone(activated.initial_password_expires_at)

                # CLI parser rejects --apply without --user-id and supports read-only --list-admins.
                with self.assertRaises(SystemExit):
                    recovery.main(["--list-admins", "--apply"])

                stdout = io.StringIO()
                with (
                    patch.object(recovery, "configure_database"),
                    patch.object(recovery.Settings, "from_env", return_value=runtime_settings),
                    patch.object(recovery, "get_session_factory", return_value=factory),
                    patch.object(
                        recovery,
                        "get_engine",
                        return_value=SimpleNamespace(dispose=AsyncMock()),
                    ),
                    redirect_stdout(stdout),
                ):
                    code = await recovery.run(
                        recovery.build_parser().parse_args(["--list-admins"])
                    )
                self.assertEqual(code, 0)
                self.assertIn(f"user_id={admin.id}", stdout.getvalue())
            finally:
                await engine.dispose()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
