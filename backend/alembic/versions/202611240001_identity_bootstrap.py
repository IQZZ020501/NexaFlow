"""Fence completed admin bootstrap and retire previously issued managed passwords."""

import secrets

import sqlalchemy as sa
from pwdlib import PasswordHash

from alembic import op

revision = "202611240001"
down_revision = "202611230001"
branch_labels = None
depends_on = None


def upgrade():
    state = op.create_table(
        "bootstrap_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.CheckConstraint("id = 1", name="ck_bootstrap_state_singleton"),
    )
    op.add_column("users", sa.Column("initial_password_expires_at", sa.DateTime(timezone=True)))
    users = sa.table(
        "users", sa.column("id"), sa.column("must_change_password"), sa.column("password_hash")
    )
    audit = sa.table("audit_logs", sa.column("action"), sa.column("resource_type"), sa.column("resource_id"))
    sessions = sa.table("refresh_sessions", sa.column("user_id"))
    db = op.get_bind()
    if db.scalar(sa.select(users.c.id).limit(1)) is None:
        return
    db.execute(state.insert().values(id=1))
    # Both provisioning endpoints recorded user.create in the credential's
    # creation transaction. The bootstrap account has no such event. Old
    # rotations of the environment password are no longer available on upgrade.
    managed = sa.select(audit.c.resource_id).where(
        audit.c.action == "user.create", audit.c.resource_type == "user"
    )
    # Older templates also shipped these bootstrap passwords. Retire them
    # only while still awaiting activation; preserve operator-chosen passwords.
    password_hasher = PasswordHash.recommended()
    known_bootstrap_defaults = ("NexaFlow@123..", "CHANGE_ME_Admin_123!")
    bootstrap_ids = [
        user_id
        for user_id, password_hash in db.execute(
            sa.select(users.c.id, users.c.password_hash).where(
                users.c.must_change_password.is_(True), users.c.id.not_in(managed)
            )
        )
        if password_hash.startswith("$argon2")
        and any(password_hasher.verify(value, password_hash) for value in known_bootstrap_defaults)
    ]
    pending = users.c.must_change_password.is_(True) & (
        users.c.id.in_(managed) | users.c.id.in_(bootstrap_ids)
    )
    db.execute(sessions.delete().where(sessions.c.user_id.in_(sa.select(users.c.id).where(pending))))
    # No plaintext corresponding to this replacement hash is retained or issued.
    # Password reset and admin recovery continue to use the standard hash format.
    retired_hash = password_hasher.hash(secrets.token_urlsafe(48))
    db.execute(users.update().where(pending).values(password_hash=retired_hash))


def downgrade():
    # Retired credentials and revoked sessions are intentionally not recoverable.
    op.drop_column("users", "initial_password_expires_at")
    op.drop_table("bootstrap_state")
