"""Refresh the PPTX catalog after removing its obsolete rendering implementations."""

from dataclasses import asdict, replace
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "202611170002"
down_revision = "202611170001"
branch_labels = None
depends_on = None


def upgrade():
    from app.domain.tools.catalog.service import build_skill_artifact_tool

    bind = op.get_bind()
    metadata = sa.MetaData()
    tools, versions, policies, bindings = (
        sa.Table(name, metadata, autoload_with=bind)
        for name in (
            "tools",
            "tool_versions",
            "tool_policies",
            "application_tool_bindings",
        )
    )
    rows = bind.execute(
        sa.select(tools.c.id, tools.c.workspace_id, tools.c.current_version_id).where(
            tools.c.kind == "builtin", tools.c.function_name == "pptx_skill"
        )
    ).all()
    timestamp = datetime.now(UTC)
    for row in rows:
        tool, version, policy = build_skill_artifact_tool(row.workspace_id, "pptx")
        if tool.id != row.id:
            continue
        if (
            bind.scalar(sa.select(versions.c.id).where(versions.c.id == version.id))
            is None
        ):
            next_revision = bind.scalar(
                sa.select(
                    sa.func.coalesce(sa.func.max(versions.c.revision), 0) + 1
                ).where(versions.c.tool_id == tool.id)
            )
            bind.execute(
                versions.insert().values(
                    **asdict(
                        replace(version, revision=next_revision, created_at=timestamp)
                    )
                )
            )
        existing_policy = (
            bind.execute(
                sa.select(policies).where(
                    policies.c.workspace_id == row.workspace_id,
                    policies.c.tool_id == tool.id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing_policy is None:
            bind.execute(policies.insert().values(**asdict(policy)))
        elif (
            existing_policy["tool_version_id"] != version.id
            or existing_policy["definition_hash"] != version.definition_hash
        ):
            bind.execute(
                policies.update()
                .where(policies.c.id == existing_policy["id"])
                .values(
                    tool_version_id=version.id,
                    definition_hash=version.definition_hash,
                    revision=existing_policy["revision"] + 1,
                    updated_at=timestamp,
                )
            )
        if row.current_version_id != version.id:
            bind.execute(
                tools.update()
                .where(tools.c.id == tool.id)
                .values(
                    current_version_id=version.id,
                    updated_at=timestamp,
                )
            )
        bind.execute(
            bindings.update()
            .where(
                bindings.c.workspace_id == row.workspace_id,
                bindings.c.tool_id == tool.id,
                bindings.c.tool_version_id != version.id,
            )
            .values(tool_version_id=version.id)
        )


def downgrade():
    """Retain immutable tool definitions and historical execution snapshots."""
