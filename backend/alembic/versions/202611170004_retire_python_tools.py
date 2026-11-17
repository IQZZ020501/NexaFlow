"""Retire standalone Python Tools and the Workflow Python code capability.

Keep versions, grants and execution/publication snapshots for historical reads.
Python-only editable drafts and mutable application bindings are removed.
Downgrade deliberately leaves retired capabilities disabled; restoring old code must not silently reauthorize
code execution or reconstruct deleted bindings.
"""

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "202611170004"
down_revision = "202611170003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    metadata = sa.MetaData()
    tools, sources, bindings = (
        sa.Table(name, metadata, autoload_with=bind)
        for name in ("tools", "tool_sources", "application_tool_bindings")
    )
    retired = sa.or_(
        tools.c.kind == "python",
        sa.and_(tools.c.kind == "builtin", tools.c.function_name == "inline_python"),
    )
    bind.execute(
        bindings.delete().where(
            bindings.c.tool_id.in_(sa.select(tools.c.id).where(retired))
        )
    )
    drafts = sa.Table("tool_drafts", metadata, autoload_with=bind)
    drafts.drop(bind)
    timestamp = datetime.now(UTC)
    bind.execute(
        tools.update()
        .where(retired)
        .values(status="archived", availability="unavailable", updated_at=timestamp)
    )
    bind.execute(
        sources.update()
        .where(sources.c.kind == "python")
        .values(status="archived", updated_at=timestamp)
    )


def downgrade():
    # A rollback must not silently restore execution permissions.
    pass
