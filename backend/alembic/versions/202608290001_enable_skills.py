"""Enable managed Skill selection for the built-in Python runtimes."""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision: str = "202608290001"
down_revision: str | None = "202608250007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _desired(stable_key: str, workspace_id: str):
    from app.shareddomain.tools.catalog import (
        build_artifact_tool,
        build_inline_python_tool,
    )

    if stable_key in {"artifact", "python_artifact"}:
        return build_artifact_tool(workspace_id)
    return build_inline_python_tool(workspace_id)


def _switch(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    bindings = sa.Table("application_tool_bindings", metadata, autoload_with=bind)
    timestamp = datetime.now(UTC)
    rows = bind.execute(
        sa.select(tools.c.id, tools.c.workspace_id, tools.c.stable_key, tools.c.current_version_id)
        .where(
            tools.c.kind == "builtin",
            tools.c.stable_key.in_(["artifact", "python_artifact", "inline_python"]),
        )
    ).all()
    for tool_id, workspace_id, stable_key, current_version_id in rows:
        if current_version_id is None:
            continue
        current = bind.execute(
            sa.select(versions.c.revision, versions.c.definition_hash)
            .where(versions.c.id == current_version_id)
        ).first()
        if current is None:
            continue
        if downgrade:
            previous = bind.execute(
                sa.select(versions.c.id, versions.c.definition_hash)
                .where(
                    versions.c.workspace_id == workspace_id,
                    versions.c.tool_id == tool_id,
                    versions.c.revision < current.revision,
                )
                .order_by(versions.c.revision.desc())
            ).first()
            if previous is None:
                continue
            version_id, version_hash = previous
        else:
            _desired_tool, desired_version, _desired_policy = _desired(
                stable_key,
                workspace_id,
            )
            if desired_version.definition_hash == current.definition_hash:
                continue
            version_id = desired_version.id
            version_hash = desired_version.definition_hash
            if bind.scalar(sa.select(versions.c.id).where(versions.c.id == version_id)) is None:
                desired_version.revision = (
                    bind.scalar(
                        sa.select(sa.func.max(versions.c.revision)).where(
                            versions.c.tool_id == tool_id
                        )
                    )
                    or 0
                ) + 1
                values = asdict(desired_version)
                values["tool_id"] = tool_id
                values["created_at"] = timestamp
                bind.execute(versions.insert().values(**values))

        bind.execute(
            policies.update()
            .where(policies.c.workspace_id == workspace_id, policies.c.tool_id == tool_id)
            .values(
                tool_version_id=version_id,
                definition_hash=version_hash,
                revision=policies.c.revision + 1,
                updated_at=timestamp,
            )
        )
        bind.execute(
            bindings.update()
            .where(bindings.c.workspace_id == workspace_id, bindings.c.tool_id == tool_id)
            .values(tool_version_id=version_id)
        )
        bind.execute(
            tools.update()
            .where(tools.c.workspace_id == workspace_id, tools.c.id == tool_id)
            .values(current_version_id=version_id, updated_at=timestamp)
        )


def upgrade() -> None:
    _switch()


def downgrade() -> None:
    _switch(downgrade=True)
