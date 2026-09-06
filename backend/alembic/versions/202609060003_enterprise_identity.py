"""Add workspace-scoped enterprise identity connections."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202609060003"
down_revision: str | None = "202609060002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "enterprise_identity_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("client_secret_hint", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('feishu', 'dingtalk', 'wecom')",
            name="ck_enterprise_connections_provider",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "provider", name="uq_enterprise_connection_provider"),
    )
    op.create_index(
        op.f("ix_enterprise_identity_connections_workspace_id"),
        "enterprise_identity_connections",
        ["workspace_id"],
    )
    op.create_table(
        "enterprise_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'disabled')",
            name="ck_enterprise_identities_status",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["enterprise_identity_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "subject_id", name="uq_enterprise_identity_subject"),
        sa.UniqueConstraint("connection_id", "user_id", name="uq_enterprise_identity_user"),
    )
    op.create_index(
        op.f("ix_enterprise_identities_connection_id"),
        "enterprise_identities",
        ["connection_id"],
    )
    op.create_index(op.f("ix_enterprise_identities_user_id"), "enterprise_identities", ["user_id"])
    op.create_table(
        "enterprise_login_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("next_path", sa.String(length=2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["enterprise_identity_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_enterprise_login_states_connection_id"),
        "enterprise_login_states",
        ["connection_id"],
    )
    op.create_index(
        op.f("ix_enterprise_login_states_expires_at"),
        "enterprise_login_states",
        ["expires_at"],
    )
    op.create_index(
        op.f("ix_enterprise_login_states_state_hash"),
        "enterprise_login_states",
        ["state_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("enterprise_login_states")
    op.drop_table("enterprise_identities")
    op.drop_table("enterprise_identity_connections")
