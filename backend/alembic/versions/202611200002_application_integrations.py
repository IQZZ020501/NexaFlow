"""Add opt-in, owner-scoped third-party application connections."""

import sqlalchemy as sa

from alembic import op

revision = "202611200002"
down_revision = "202611200001"
branch_labels = None
depends_on = None


def _tool_constraints(include_integrations):
    kinds = "'builtin', 'python', 'mcp'" + (
        ", 'integration'" if include_integrations else ""
    )
    local_kinds = "'builtin', 'python'" + (
        ", 'integration'" if include_integrations else ""
    )
    with op.batch_alter_table("tool_sources") as batch:
        batch.drop_constraint("ck_tool_sources_kind", type_="check")
        batch.create_check_constraint("ck_tool_sources_kind", f"kind IN ({kinds})")
        batch.drop_constraint("ck_tool_sources_mcp_server_kind", type_="check")
        batch.create_check_constraint(
            "ck_tool_sources_mcp_server_kind",
            "(kind = 'mcp' AND ((mcp_server_id IS NOT NULL AND status IN ('active', 'disabled')) OR (mcp_server_id IS NULL AND status = 'archived'))) OR "
            + f"(kind IN ({local_kinds}) AND mcp_server_id IS NULL)",
        )
    with op.batch_alter_table("tools") as batch:
        batch.drop_constraint("ck_tools_kind", type_="check")
        batch.create_check_constraint("ck_tools_kind", f"kind IN ({kinds})")


def upgrade():
    _tool_constraints(True)
    op.create_table(
        "integration_applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("client_id", sa.String(256), nullable=False),
        sa.Column("client_secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "provider"),
    )
    op.create_table(
        "integration_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(36)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("application_revision", sa.Integer(), nullable=False),
        sa.Column("secrets_ciphertext", sa.Text(), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True)),
        sa.Column("refreshable", sa.Boolean(), nullable=False),
        sa.Column("refresh_owner", sa.String(36)),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", "provider"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["tool_sources.workspace_id", "tool_sources.id"],
        ),
    )
    op.create_index(
        "ix_integration_connections_user_id", "integration_connections", ["user_id"]
    )
    op.create_table(
        "integration_authorizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("integration_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("secrets_ciphertext", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.String(2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_integration_authorizations_connection_id",
        "integration_authorizations",
        ["connection_id"],
    )
    op.create_index(
        "ix_integration_authorizations_expires_at",
        "integration_authorizations",
        ["expires_at"],
    )


def downgrade():
    # Do not erase private grants or immutable execution history on downgrade.
    bind = op.get_bind()
    for table in ("integration_connections", "integration_applications"):
        if bind.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError(
                "Remove integration connections and application configuration before downgrading."
            )
    if bind.scalar(
        sa.text("SELECT COUNT(*) FROM tool_sources WHERE kind = 'integration'")
    ):
        raise RuntimeError("Integration tool history prevents a lossless downgrade.")
    op.drop_table("integration_authorizations")
    op.drop_table("integration_connections")
    op.drop_table("integration_applications")
    _tool_constraints(False)
