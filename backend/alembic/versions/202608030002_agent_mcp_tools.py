"""agent MCP tools

Revision ID: 202608030002
Revises: 202608030001
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608030002"
down_revision: str | None = "202608030001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("bearer_token_ciphertext", sa.Text(), nullable=True),
        sa.Column("bearer_token_hint", sa.String(length=32), nullable=True),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_mcp_servers_status",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_mcp_servers_workspace_id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_mcp_servers_workspace_name"),
    )
    op.create_index(
        op.f("ix_mcp_servers_created_by_user_id"),
        "mcp_servers",
        ["created_by_user_id"],
    )
    op.create_index(
        op.f("ix_mcp_servers_workspace_id"),
        "mcp_servers",
        ["workspace_id"],
    )

    op.create_table(
        "agent_mcp_tools",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("mcp_server_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_mcp_tools_agent_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "mcp_server_id"],
            ["mcp_servers.workspace_id", "mcp_servers.id"],
            name="fk_agent_mcp_tools_server_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "mcp_server_id",
            "tool_name",
            name="uq_agent_mcp_tools_binding",
        ),
    )
    op.create_index(
        op.f("ix_agent_mcp_tools_agent_id"),
        "agent_mcp_tools",
        ["agent_id"],
    )
    op.create_index(
        op.f("ix_agent_mcp_tools_mcp_server_id"),
        "agent_mcp_tools",
        ["mcp_server_id"],
    )
    op.create_index(
        op.f("ix_agent_mcp_tools_workspace_id"),
        "agent_mcp_tools",
        ["workspace_id"],
    )

    op.add_column(
        "agent_runs",
        sa.Column(
            "mcp_tools",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column(
            "agent_runs",
            "mcp_tools",
            existing_type=sa.JSON(),
            server_default=None,
        )


def downgrade() -> None:
    op.drop_column("agent_runs", "mcp_tools")
    op.drop_index(op.f("ix_agent_mcp_tools_workspace_id"), table_name="agent_mcp_tools")
    op.drop_index(op.f("ix_agent_mcp_tools_mcp_server_id"), table_name="agent_mcp_tools")
    op.drop_index(op.f("ix_agent_mcp_tools_agent_id"), table_name="agent_mcp_tools")
    op.drop_table("agent_mcp_tools")
    op.drop_index(op.f("ix_mcp_servers_workspace_id"), table_name="mcp_servers")
    op.drop_index(op.f("ix_mcp_servers_created_by_user_id"), table_name="mcp_servers")
    op.drop_table("mcp_servers")
