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


def downgrade() -> None:
    op.drop_constraint(NETWORK_POLICY_CHECK, "mcp_servers", type_="check")
    op.drop_column("mcp_servers", "network_policy")
