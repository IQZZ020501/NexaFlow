"""Refresh existing built-in file delivery definitions without widening access."""

from dataclasses import asdict, replace
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "202611170001"
down_revision = "202611160006"
branch_labels = None
depends_on = None


def upgrade():
    from app.domain.tools.catalog.service import (
        build_image_generation_tool,
        build_shell_tool,
        build_skill_artifact_tool,
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    tools, versions, policies, bindings = (
        sa.Table(name, metadata, autoload_with=bind)
        for name in ("tools", "tool_versions", "tool_policies", "application_tool_bindings")
    )
    rows = bind.execute(
        sa.select(tools.c.id, tools.c.workspace_id, tools.c.current_version_id)
        .where(tools.c.kind == "builtin")
    ).all()
    by_workspace = {}
    for row in rows:
        by_workspace.setdefault(row.workspace_id, {})[row.id] = row.current_version_id

    timestamp = datetime.now(UTC)
    for workspace_id, current in by_workspace.items():
        desired = [
            build_shell_tool(workspace_id),
            build_image_generation_tool(workspace_id),
            *(build_skill_artifact_tool(workspace_id, skill)
              for skill in ("documents", "pdf", "pptx", "spreadsheets")),
        ]
        for tool, version, policy in desired:
            if tool.id not in current:
                continue
            if bind.scalar(sa.select(versions.c.id).where(versions.c.id == version.id)) is None:
                next_revision = bind.scalar(
                    sa.select(sa.func.coalesce(sa.func.max(versions.c.revision), 0) + 1)
                    .where(versions.c.tool_id == tool.id)
                )
                bind.execute(versions.insert().values(**asdict(replace(
                    version, revision=next_revision, created_at=timestamp,
                ))))
            existing_policy = bind.execute(
                sa.select(policies).where(
                    policies.c.workspace_id == workspace_id, policies.c.tool_id == tool.id,
                )
            ).mappings().one_or_none()
            if existing_policy is None:
                bind.execute(policies.insert().values(**asdict(policy)))
            elif (
                existing_policy["tool_version_id"] != version.id
                or existing_policy["definition_hash"] != version.definition_hash
            ):
                # Move only the reviewed definition; keep approval, access and all
                # other operator-owned policy values, including disabled tools.
                bind.execute(policies.update().where(policies.c.id == existing_policy["id"]).values(
                    tool_version_id=version.id, definition_hash=version.definition_hash,
                    revision=existing_policy["revision"] + 1, updated_at=timestamp,
                ))
            previous_version = current[tool.id]
            if previous_version == version.id:
                continue
            bind.execute(tools.update().where(tools.c.id == tool.id).values(
                current_version_id=version.id, updated_at=timestamp,
            ))
            # These changes retain existing input contracts and add delivery
            # metadata/instructions. Advance mutable bindings from the previous
            # current version only; never rewrite publication or Run snapshots.
            if previous_version is not None:
                bind.execute(bindings.update().where(
                    bindings.c.workspace_id == workspace_id,
                    bindings.c.tool_id == tool.id,
                    bindings.c.tool_version_id == previous_version,
                ).values(tool_version_id=version.id))


def downgrade():
    """Keep immutable versions and historical execution snapshots."""
