"""Version built-in authoring guides and add the Skill Creator to existing workspaces."""

from dataclasses import asdict, replace
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "202611170003"
down_revision = "202611170002"
branch_labels = None
depends_on = None


def upgrade():
    from app.domain.tools.catalog.service import (
        BUILTIN_SKILL_DEFINITIONS,
        build_skill_artifact_tool,
    )

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
    workspace_ids = (
        bind.execute(
            sa.select(tools.c.workspace_id).where(tools.c.kind == "builtin").distinct()
        )
        .scalars()
        .all()
    )
    timestamp = datetime.now(UTC)
    for workspace_id, skill_name in (
        (workspace_id, definition[0])
        for workspace_id in workspace_ids
        for definition in BUILTIN_SKILL_DEFINITIONS
    ):
        tool, version, policy = build_skill_artifact_tool(workspace_id, skill_name)
        existing_tool = (
            bind.execute(sa.select(tools).where(tools.c.id == tool.id))
            .mappings()
            .one_or_none()
        )
        if existing_tool is None:
            bind.execute(
                tools.insert().values(**asdict(replace(tool, current_version_id=None)))
            )
        if (
            bind.scalar(sa.select(versions.c.id).where(versions.c.id == version.id))
            is None
        ):
            next_revision = bind.scalar(
                sa.select(
                    sa.func.coalesce(sa.func.max(versions.c.revision), 0) + 1,
                ).where(versions.c.tool_id == tool.id)
            )
            bind.execute(
                versions.insert().values(
                    **asdict(
                        replace(
                            version,
                            revision=next_revision,
                            created_at=timestamp,
                        )
                    )
                )
            )
        existing_policy = (
            bind.execute(
                sa.select(policies).where(
                    policies.c.workspace_id == workspace_id,
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
            or existing_policy["workflow_callable"]
        ):
            bind.execute(
                policies.update()
                .where(policies.c.id == existing_policy["id"])
                .values(
                    tool_version_id=version.id,
                    definition_hash=version.definition_hash,
                    revision=existing_policy["revision"] + 1,
                    workflow_callable=False,
                    updated_at=timestamp,
                )
            )
        if existing_tool is None or existing_tool["current_version_id"] != version.id:
            bind.execute(
                tools.update()
                .where(tools.c.id == tool.id)
                .values(
                    current_version_id=version.id,
                    updated_at=timestamp,
                )
            )
        # Mutable application bindings follow the new instruction contract. Publication and Run snapshots keep their frozen history.
        bind.execute(
            bindings.update()
            .where(
                bindings.c.workspace_id == workspace_id,
                bindings.c.tool_id == tool.id,
                bindings.c.tool_version_id != version.id,
            )
            .values(tool_version_id=version.id)
        )


def downgrade():
    """Retain immutable tool definitions and historical execution snapshots."""
