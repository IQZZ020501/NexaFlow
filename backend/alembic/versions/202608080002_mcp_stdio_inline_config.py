"""Store inline MCP stdio configuration

Revision ID: 202608080002
Revises: 202608080001
Create Date: 2026-08-08
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608080002"
down_revision: str | None = "202608080001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONFIGURATION_CHECK = "ck_mcp_servers_transport_configuration"


def upgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_constraint(CONFIGURATION_CHECK, type_="check")
        batch.add_column(sa.Column("stdio_command", sa.Text(), nullable=True))
        batch.add_column(sa.Column("stdio_config_ciphertext", sa.Text(), nullable=True))

    op.execute(
        "UPDATE mcp_servers SET status = 'disabled', "
        "last_error = 'Legacy stdio profile must be recreated with inline configuration: ' "
        "|| stdio_profile WHERE transport = 'stdio'"
    )

    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_column("stdio_profile_fingerprint")
        batch.drop_column("stdio_profile")
        batch.create_check_constraint(
            CONFIGURATION_CHECK,
            "(transport IN ('streamable_http', 'sse') AND url IS NOT NULL "
            "AND stdio_command IS NULL AND stdio_config_ciphertext IS NULL) OR "
            "(transport = 'stdio' AND url IS NULL "
            "AND bearer_token_ciphertext IS NULL AND bearer_token_hint IS NULL AND "
            "((stdio_command IS NOT NULL AND stdio_config_ciphertext IS NOT NULL) OR "
            "(status = 'disabled' AND stdio_command IS NULL "
            "AND stdio_config_ciphertext IS NULL)))",
        )


def downgrade() -> None:
    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_constraint(CONFIGURATION_CHECK, type_="check")
        batch.add_column(sa.Column("stdio_profile", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("stdio_profile_fingerprint", sa.String(length=64), nullable=True)
        )

    op.execute(
        "UPDATE mcp_servers SET status = 'disabled', "
        "stdio_profile = CASE WHEN stdio_command IS NOT NULL "
        "THEN 'inline-' || id ELSE 'legacy-disabled' END, "
        "stdio_profile_fingerprint = '', "
        "last_error = 'stdio registration must be recreated after downgrade' "
        "WHERE transport = 'stdio'"
    )

    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_column("stdio_config_ciphertext")
        batch.drop_column("stdio_command")
        batch.create_check_constraint(
            CONFIGURATION_CHECK,
            "(transport IN ('streamable_http', 'sse') AND url IS NOT NULL "
            "AND stdio_profile IS NULL AND stdio_profile_fingerprint IS NULL) OR "
            "(transport = 'stdio' AND url IS NULL AND stdio_profile IS NOT NULL "
            "AND stdio_profile_fingerprint IS NOT NULL "
            "AND bearer_token_ciphertext IS NULL AND bearer_token_hint IS NULL)",
        )
