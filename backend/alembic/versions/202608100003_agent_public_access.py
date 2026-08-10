"""Add Agent publication identity, external consumers, and API credentials."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202608100003"
down_revision: str | None = "202608100002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIGRATION_ACTIVE_RUN_STATUSES = (
    "queued",
    "planning",
    "planned",
    "running",
    "awaiting_approval",
)


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(
            sa.Column("published_by_user_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
        )

    # Previous rows do not have a verifiable publishing actor. Requiring an
    # explicit republish avoids silently granting that actor's model/tool access.
    op.execute(
        sa.text(
            "UPDATE agents SET published = false, "
            "published_by_user_id = NULL, published_at = NULL"
        )
    )
    with op.batch_alter_table("agents") as batch:
        batch.create_foreign_key(
            "fk_agents_published_by_user_id",
            "users",
            ["published_by_user_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "ck_agents_publication",
            "(published = false AND published_by_user_id IS NULL AND published_at IS NULL) "
            "OR (published = true AND published_by_user_id IS NOT NULL AND published_at IS NOT NULL)",
        )
        batch.create_index(
            "ix_agents_published_by_user_id",
            ["published_by_user_id"],
        )

    op.create_table(
        "agent_api_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("hint", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "agent_id"],
            ["agents.workspace_id", "agents.id"],
            name="fk_agent_api_credentials_agent_workspace",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_agent_api_credentials_token_hash"),
    )
    op.create_index(
        "ix_agent_api_credentials_workspace_id",
        "agent_api_credentials",
        ["workspace_id"],
    )
    op.create_index(
        "ix_agent_api_credentials_agent_id",
        "agent_api_credentials",
        ["agent_id"],
    )
    op.create_index(
        "ix_agent_api_credentials_token_hash",
        "agent_api_credentials",
        ["token_hash"],
    )
    op.create_index(
        "ix_agent_api_credentials_created_by_user_id",
        "agent_api_credentials",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_agent_api_credentials_revoked_at",
        "agent_api_credentials",
        ["revoked_at"],
    )

    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(
            sa.Column("execution_user_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "access_source",
                sa.String(length=20),
                nullable=True,
                server_default="console",
            )
        )
        batch.add_column(sa.Column("consumer_id", sa.String(length=64), nullable=True))
        batch.alter_column("requested_by_user_id", nullable=True)

    op.execute(
        sa.text(
            "UPDATE agent_runs SET execution_user_id = requested_by_user_id, "
            "access_source = 'console', consumer_id = requested_by_user_id"
        )
    )
    with op.batch_alter_table("agent_runs") as batch:
        batch.alter_column("execution_user_id", nullable=False)
        batch.alter_column("access_source", nullable=False, server_default=None)
        batch.alter_column("consumer_id", nullable=False)
        batch.create_foreign_key(
            "fk_agent_runs_execution_user_id",
            "users",
            ["execution_user_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "ck_agent_runs_access_source",
            "access_source IN ('console', 'public', 'api')",
        )
        batch.create_check_constraint(
            "ck_agent_runs_access_identity",
            "(access_source = 'console' AND requested_by_user_id IS NOT NULL "
            "AND consumer_id = requested_by_user_id "
            "AND execution_user_id = requested_by_user_id) OR "
            "(access_source IN ('public', 'api') AND requested_by_user_id IS NULL)",
        )
        batch.create_index("ix_agent_runs_execution_user_id", ["execution_user_id"])
        batch.create_index("ix_agent_runs_access_source", ["access_source"])
        batch.create_index("ix_agent_runs_consumer_id", ["consumer_id"])

    op.create_index(
        "uq_agent_runs_active_conversation",
        "agent_runs",
        [
            "workspace_id",
            "agent_id",
            "access_source",
            "consumer_id",
            "conversation_id",
        ],
        unique=True,
        postgresql_where=sa.column("status").in_(MIGRATION_ACTIVE_RUN_STATUSES),
        sqlite_where=sa.column("status").in_(MIGRATION_ACTIVE_RUN_STATUSES),
    )


def _delete_external_runs(bind: sa.engine.Connection) -> None:
    external_run_ids = (
        "SELECT id FROM agent_runs WHERE requested_by_user_id IS NULL"
    )
    bind.execute(
        sa.text(
            "DELETE FROM agent_tool_calls WHERE run_id IN (" + external_run_ids + ")"
        )
    )
    bind.execute(
        sa.text(
            "DELETE FROM agent_run_events WHERE run_id IN (" + external_run_ids + ")"
        )
    )
    bind.execute(
        sa.text("DELETE FROM agent_runs WHERE requested_by_user_id IS NULL")
    )


def downgrade() -> None:
    op.drop_index("uq_agent_runs_active_conversation", table_name="agent_runs")
    _delete_external_runs(op.get_bind())
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_index("ix_agent_runs_consumer_id")
        batch.drop_index("ix_agent_runs_access_source")
        batch.drop_index("ix_agent_runs_execution_user_id")
        batch.drop_constraint("ck_agent_runs_access_identity", type_="check")
        batch.drop_constraint("ck_agent_runs_access_source", type_="check")
        batch.drop_constraint("fk_agent_runs_execution_user_id", type_="foreignkey")
        batch.alter_column("requested_by_user_id", nullable=False)
        batch.drop_column("consumer_id")
        batch.drop_column("access_source")
        batch.drop_column("execution_user_id")
    op.create_index(
        "uq_agent_runs_active_conversation",
        "agent_runs",
        ["workspace_id", "agent_id", "requested_by_user_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.column("status").in_(MIGRATION_ACTIVE_RUN_STATUSES),
        sqlite_where=sa.column("status").in_(MIGRATION_ACTIVE_RUN_STATUSES),
    )

    op.drop_index(
        "ix_agent_api_credentials_revoked_at",
        table_name="agent_api_credentials",
    )
    op.drop_index(
        "ix_agent_api_credentials_created_by_user_id",
        table_name="agent_api_credentials",
    )
    op.drop_index(
        "ix_agent_api_credentials_token_hash",
        table_name="agent_api_credentials",
    )
    op.drop_index(
        "ix_agent_api_credentials_agent_id",
        table_name="agent_api_credentials",
    )
    op.drop_index(
        "ix_agent_api_credentials_workspace_id",
        table_name="agent_api_credentials",
    )
    op.drop_table("agent_api_credentials")

    with op.batch_alter_table("agents") as batch:
        batch.drop_index("ix_agents_published_by_user_id")
        batch.drop_constraint("ck_agents_publication", type_="check")
        batch.drop_constraint("fk_agents_published_by_user_id", type_="foreignkey")
        batch.drop_column("published_at")
        batch.drop_column("published_by_user_id")
