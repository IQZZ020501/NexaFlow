"""Persist MCP network trust policy.

Revision ID: 202608160004
Revises: 202608160003
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202608160004"
down_revision: str | None = "202608160003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NETWORK_POLICY_CHECK = "ck_mcp_servers_network_policy"
RESOURCE_PERMISSION_MEMBERSHIP_FK = "fk_resource_permission_workspace_user"


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "network_policy",
            sa.String(length=20),
            nullable=False,
            server_default="deployment",
        ),
    )
    op.create_check_constraint(
        NETWORK_POLICY_CHECK,
        "mcp_servers",
        "network_policy IN ('public_only', 'deployment')",
    )
    op.alter_column(
        "mcp_servers",
        "network_policy",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        server_default="public_only",
    )
    op.drop_constraint(
        RESOURCE_PERMISSION_MEMBERSHIP_FK,
        "resource_permissions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        RESOURCE_PERMISSION_MEMBERSHIP_FK,
        "resource_permissions",
        "workspace_memberships",
        ["workspace_id", "user_id"],
        ["workspace_id", "user_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        RESOURCE_PERMISSION_MEMBERSHIP_FK,
        "resource_permissions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        RESOURCE_PERMISSION_MEMBERSHIP_FK,
        "resource_permissions",
        "workspace_memberships",
        ["workspace_id", "user_id"],
        ["workspace_id", "user_id"],
    )
    op.drop_constraint(NETWORK_POLICY_CHECK, "mcp_servers", type_="check")
    op.drop_column("mcp_servers", "network_policy")
