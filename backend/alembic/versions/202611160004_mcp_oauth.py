"""Persist MCP PKCE attempts, coordinated token rotation and revocation intent."""

import sqlalchemy as sa

from alembic import op

revision = "202611160004"
down_revision = "202611160003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mcp_servers",
        sa.Column("auth_mode", sa.String(12), nullable=False, server_default="bearer"),
    )
    op.create_table(
        "mcp_oauth_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "server_id",
            sa.String(36),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("secrets_ciphertext", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True)),
        sa.Column("refresh_owner", sa.String(36)),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "mcp_oauth_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("mcp_oauth_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_mcp_oauth_attempts_expires_at", "mcp_oauth_attempts", ["expires_at"]
    )
    op.create_table(
        "mcp_oauth_revocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("secrets_ciphertext", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_mcp_oauth_revocations_due", "mcp_oauth_revocations", ["next_attempt_at"]
    )


def downgrade():
    op.drop_table("mcp_oauth_revocations")
    op.drop_table("mcp_oauth_attempts")
    op.drop_table("mcp_oauth_connections")
    op.drop_column("mcp_servers", "auth_mode")
