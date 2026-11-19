"""Align stale MCP policies with current definitions for conversation approval."""

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "202611190003"
down_revision = "202611190002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    tools, sources, versions, policies = (
        sa.Table(name, metadata, autoload_with=bind)
        for name in ("tools", "tool_sources", "tool_versions", "tool_policies")
    )
    rows = bind.execute(
        sa.select(
            policies.c.id,
            policies.c.revision,
            policies.c.approval,
            tools.c.status.label("tool_status"),
            versions.c.id.label("version_id"),
            versions.c.definition_hash,
        )
        .select_from(
            tools.join(
                sources,
                sa.and_(
                    tools.c.source_id == sources.c.id,
                    tools.c.workspace_id == sources.c.workspace_id,
                ),
            )
            .join(
                versions,
                sa.and_(
                    tools.c.current_version_id == versions.c.id,
                    tools.c.id == versions.c.tool_id,
                    tools.c.workspace_id == versions.c.workspace_id,
                ),
            )
            .join(
                policies,
                sa.and_(
                    tools.c.id == policies.c.tool_id,
                    tools.c.workspace_id == policies.c.workspace_id,
                ),
            )
        )
        .where(
            tools.c.kind == "mcp",
            sources.c.kind == "mcp",
            tools.c.status.in_(["active", "disabled"]),
            sources.c.status.in_(["active", "disabled"]),
            tools.c.availability == "available",
            sa.or_(
                policies.c.tool_version_id != versions.c.id,
                policies.c.definition_hash != versions.c.definition_hash,
            ),
        )
    ).all()
    timestamp = datetime.now(UTC)
    for row in rows:
        disabled = row.approval == "disabled" or row.tool_status == "disabled"
        bind.execute(
            policies.update()
            .where(policies.c.id == row.id)
            .values(
                tool_version_id=row.version_id,
                definition_hash=row.definition_hash,
                revision=row.revision + 1,
                approval="disabled" if disabled else "each_call",
                effect="unknown",
                allowed_access_sources=[] if disabled else ["console", "public"],
                workflow_callable=not disabled,
                parallel_safe=False,
                reviewed_by_user_id=None,
                reviewed_at=None,
                updated_at=timestamp,
            )
        )


def downgrade():
    """Do not restore automatic grants for definitions they never authorized."""
