"""Refresh the built-in Documents Skill contract with formal legal styling."""

from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision: str = "202609040001"
down_revision: str | None = "202608300003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _desired(workspace_id: str):
    from app.shareddomain.tools.catalog import build_skill_artifact_tool

    return build_skill_artifact_tool(workspace_id, "documents")


def _tables(bind: sa.Connection) -> dict[str, sa.Table]:
    metadata = sa.MetaData()
    inspector = sa.inspect(bind)
    names = ("tool_sources", "tools", "tool_versions", "tool_policies")
    return {
        name: sa.Table(name, metadata, autoload_with=bind)
        for name in names
        if inspector.has_table(name)
    }


def upgrade() -> None:
    """Point each workspace's Documents Skill at the new immutable version."""
    bind = op.get_bind()
    tables = _tables(bind)
    sources = tables["tool_sources"]
    tools = tables["tools"]
    versions = tables["tool_versions"]
    policies = tables["tool_policies"]
    workspace_ids = bind.execute(
        sa.select(sources.c.workspace_id)
        .where(sources.c.kind == "builtin")
        .distinct()
    ).scalars()
    timestamp = datetime.now(UTC)

    for workspace_id in workspace_ids:
        desired_tool, desired_version, desired_policy = _desired(workspace_id)
        if (
            bind.scalar(sa.select(tools.c.id).where(tools.c.id == desired_tool.id))
            is None
        ):
            values = asdict(desired_tool)
            values["current_version_id"] = None
            values["created_at"] = timestamp
            values["updated_at"] = timestamp
            bind.execute(tools.insert().values(**values))

        if bind.scalar(
            sa.select(versions.c.id).where(versions.c.id == desired_version.id)
        ) is None:
            next_revision = bind.execute(
                sa.select(
                    sa.func.coalesce(sa.func.max(versions.c.revision), 0) + 1
                ).where(versions.c.tool_id == desired_tool.id)
            ).scalar_one()
            desired_version = replace(desired_version, revision=next_revision)
            values = asdict(desired_version)
            values["created_at"] = timestamp
            bind.execute(versions.insert().values(**values))

        policy_id = bind.scalar(
            sa.select(policies.c.id).where(
                policies.c.workspace_id == workspace_id,
                policies.c.tool_id == desired_tool.id,
            )
        )
        if policy_id is None:
            values = asdict(desired_policy)
            values["created_at"] = timestamp
            values["updated_at"] = timestamp
            bind.execute(policies.insert().values(**values))
        else:
            bind.execute(
                policies.update()
                .where(policies.c.id == policy_id)
                .values(
                    tool_version_id=desired_version.id,
                    definition_hash=desired_version.definition_hash,
                    approval=desired_policy.approval,
                    effect=desired_policy.effect,
                    allowed_access_sources=desired_policy.allowed_access_sources,
                    workflow_callable=desired_policy.workflow_callable,
                    parallel_safe=desired_policy.parallel_safe,
                    updated_at=timestamp,
                )
            )

        bind.execute(
            tools.update()
            .where(
                tools.c.workspace_id == workspace_id,
                tools.c.id == desired_tool.id,
            )
            .values(
                current_version_id=desired_version.id,
                status="active",
                availability="available",
                updated_at=timestamp,
            )
        )


def downgrade() -> None:
    """Retain the content-addressed version and current pointer."""
