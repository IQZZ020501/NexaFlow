"""Scope user-configured MCP and Skill names to their owner."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610250003"
down_revision: str | None = "202610250002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINTS = (
    (
        "mcp_servers",
        "uq_mcp_servers_workspace_name",
        "uq_mcp_servers_owner_name",
        ("workspace_id", "name"),
    ),
    (
        "agent_skills",
        "uq_agent_skills_workspace_name",
        "uq_agent_skills_owner_name",
        ("workspace_id", "name"),
    ),
    (
        "tool_sources",
        "uq_tool_sources_workspace_kind_name",
        "uq_tool_sources_owner_kind_name",
        ("workspace_id", "kind", "name"),
    ),
)


def upgrade() -> None:
    for table, old_name, new_name, columns in _CONSTRAINTS:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(old_name, type_="unique")
            batch.create_unique_constraint(
                new_name, [*columns[:-1], "created_by_user_id", columns[-1]]
            )
    op.create_index(
        "uq_tool_sources_system_kind_name",
        "tool_sources",
        ["workspace_id", "kind", "name"],
        unique=True,
        postgresql_where=sa.text("created_by_user_id IS NULL"),
        sqlite_where=sa.text("created_by_user_id IS NULL"),
    )


def downgrade() -> None:
    for table_name, _, _, columns in _CONSTRAINTS:
        table = sa.table(table_name, *(sa.column(column) for column in columns))
        duplicates = (
            sa.select(sa.literal(1))
            .select_from(table)
            .group_by(*(table.c[column] for column in columns))
            .having(sa.func.count() > 1)
            .limit(1)
        )
        if op.get_bind().scalar(duplicates):
            raise RuntimeError(
                "Personal resource names conflict; rename them before downgrade."
            )
    op.drop_index("uq_tool_sources_system_kind_name", table_name="tool_sources")
    for table, old_name, new_name, columns in reversed(_CONSTRAINTS):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(new_name, type_="unique")
            batch.create_unique_constraint(old_name, list(columns))
