"""Register the approval-backed Skill dependency installer."""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "202609190001"
down_revision: str | None = "202609130001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    inspector = sa.inspect(bind)
    names = ("tool_sources", "tools", "tool_versions", "tool_policies")
    if any(not inspector.has_table(name) for name in names):
        return
    sources, tools, versions, policies = (
        sa.Table(name, metadata, autoload_with=bind) for name in names
    )
    from app.domain.tools.catalog.service import (
        build_skill_dependency_installer_tool,
    )

    workspace_ids = bind.execute(
        sa.select(sources.c.workspace_id)
        .where(sources.c.kind == "builtin")
        .distinct()
    ).scalars()
    timestamp = datetime.now(UTC)
    for workspace_id in workspace_ids:
        tool, version, policy = build_skill_dependency_installer_tool(workspace_id)
        if bind.scalar(sa.select(tools.c.id).where(tools.c.id == tool.id)) is None:
            values = asdict(tool)
            values["current_version_id"] = None
            values["created_at"] = timestamp
            values["updated_at"] = timestamp
            bind.execute(tools.insert().values(**values))
        if bind.scalar(sa.select(versions.c.id).where(versions.c.id == version.id)) is None:
            values = asdict(version)
            values["created_at"] = timestamp
            bind.execute(versions.insert().values(**values))
        if bind.scalar(sa.select(policies.c.id).where(policies.c.id == policy.id)) is None:
            values = asdict(policy)
            values["created_at"] = timestamp
            values["updated_at"] = timestamp
            bind.execute(policies.insert().values(**values))
        bind.execute(
            tools.update()
            .where(tools.c.id == tool.id)
            .values(
                current_version_id=version.id,
                status="active",
                availability="available",
                updated_at=timestamp,
            )
        )


def downgrade() -> None:
    """Retain immutable catalog and invocation history."""
