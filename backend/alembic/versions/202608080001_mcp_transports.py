"""MCP SSE and stdio transports

Revision ID: 202608080001
Revises: 202608070001
Create Date: 2026-08-08
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608080001"
down_revision: str | None = "202608070001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSPORT_CHECK = "ck_mcp_servers_transport"
CONFIGURATION_CHECK = "ck_mcp_servers_transport_configuration"


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.add_column(
            sa.Column(
                "transport",
                sa.String(length=30),
                nullable=False,
                server_default="streamable_http",
            )
        )
        batch.add_column(sa.Column("stdio_profile", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("stdio_profile_fingerprint", sa.String(length=64), nullable=True)
        )
        batch.alter_column("url", existing_type=sa.Text(), nullable=True)
        batch.create_check_constraint(
            TRANSPORT_CHECK,
            "transport IN ('streamable_http', 'sse', 'stdio')",
        )
        batch.create_check_constraint(
            CONFIGURATION_CHECK,
            "(transport IN ('streamable_http', 'sse') AND url IS NOT NULL "
            "AND stdio_profile IS NULL AND stdio_profile_fingerprint IS NULL) OR "
            "(transport = 'stdio' AND url IS NULL AND stdio_profile IS NOT NULL "
            "AND stdio_profile_fingerprint IS NOT NULL "
            "AND bearer_token_ciphertext IS NULL AND bearer_token_hint IS NULL)",
        )

    # A downgrade preserves non-HTTP registrations as inert URLs. Recover them
    # when this migration is applied again; stdio still requires an admin refresh.
    op.execute(
        "UPDATE mcp_servers SET transport = 'stdio', "
        "stdio_profile = substr(url, 9), stdio_profile_fingerprint = '', url = NULL "
        "WHERE url LIKE 'stdio://%'"
    )
    op.execute(
        "UPDATE mcp_servers SET transport = 'sse', url = substr(url, 5) "
        "WHERE url LIKE 'sse+http://%' OR url LIKE 'sse+https://%'"
    )


def downgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_constraint(CONFIGURATION_CHECK, type_="check")
        batch.drop_constraint(TRANSPORT_CHECK, type_="check")

    op.execute(
        "UPDATE mcp_servers SET url = 'stdio://' || COALESCE(stdio_profile, 'unknown') "
        "WHERE transport = 'stdio'"
    )
    op.execute(
        "UPDATE mcp_servers SET url = 'sse+' || url "
        "WHERE transport = 'sse'"
    )

    with op.batch_alter_table("mcp_servers") as batch:
        batch.alter_column("url", existing_type=sa.Text(), nullable=False)
        batch.drop_column("stdio_profile_fingerprint")
        batch.drop_column("stdio_profile")
        batch.drop_column("transport")
