"""Register the built-in Skill bundles as selectable Tool contracts."""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision: str = "202608300001"
down_revision: str | None = "202608290001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _desired(skill_name: str, workspace_id: str):
    from app.shareddomain.tools.catalog import build_skill_artifact_tool

    return build_skill_artifact_tool(workspace_id, skill_name)


def _contains_reference(value: object, tool_id: str, version_id: str) -> bool:
    if isinstance(value, dict):
        if value.get("tool_id") == tool_id and (
            value.get("version_id") == version_id
            or value.get("tool_version_id") == version_id
        ):
            return True
        return any(
            _contains_reference(child, tool_id, version_id)
            for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_reference(child, tool_id, version_id) for child in value)
    return False


def _assert_downgrade_safe(
    bind: sa.Connection,
    tool_id: str,
    version_id: str,
    tables: dict[str, sa.Table],
) -> None:
    for table_name, columns in (
        ("application_tool_bindings", ("tool_id", "tool_version_id")),
        ("tool_invocations", ("tool_id", "tool_version_id")),
    ):
        table = tables.get(table_name)
        if table is not None and bind.scalar(
            sa.select(sa.literal(True))
            .where(
                table.c[columns[0]] == tool_id,
                table.c[columns[1]] == version_id,
            )
            .limit(1)
        ):
            raise RuntimeError(
                "Cannot remove a built-in Skill Tool while it is referenced."
            )

    for table_name, column_name in (
        ("agent_publication_versions", "resource_snapshot"),
        ("agent_run_snapshots", "tool_snapshots"),
        ("workflow_versions", "resource_snapshot"),
        ("workflow_run_details", "resource_snapshot"),
        ("tool_invocations", "policy_snapshot"),
    ):
        table = tables.get(table_name)
        if table is not None and any(
            _contains_reference(value, tool_id, version_id)
            for value in bind.execute(sa.select(table.c[column_name])).scalars()
        ):
            raise RuntimeError(
                "Cannot remove a built-in Skill Tool while it is referenced."
            )


def _tables(bind: sa.Connection) -> dict[str, sa.Table]:
    metadata = sa.MetaData()
    inspector = sa.inspect(bind)
    names = (
        "tool_sources",
        "tools",
        "tool_versions",
        "tool_policies",
        "resource_permissions",
        "application_tool_bindings",
        "tool_invocations",
        "agent_publication_versions",
        "agent_run_snapshots",
        "workflow_versions",
        "workflow_run_details",
    )
    return {
        name: sa.Table(name, metadata, autoload_with=bind)
        for name in names
        if inspector.has_table(name)
    }


def upgrade() -> None:
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
        for skill_name, *_ in _skill_definitions():
            desired_tool, desired_version, desired_policy = _desired(
                skill_name,
                workspace_id,
            )
            if bind.scalar(
                sa.select(tools.c.id).where(tools.c.id == desired_tool.id)
            ) is None:
                values = asdict(desired_tool)
                values["current_version_id"] = None
                values["created_at"] = timestamp
                values["updated_at"] = timestamp
                bind.execute(tools.insert().values(**values))

            if bind.scalar(
                sa.select(versions.c.id).where(versions.c.id == desired_version.id)
            ) is None:
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
    bind = op.get_bind()
    tables = _tables(bind)
    tools = tables["tools"]
    versions = tables["tool_versions"]
    policies = tables["tool_policies"]
    permissions = tables.get("resource_permissions")
    workspace_ids = bind.execute(
        sa.select(tools.c.workspace_id)
        .where(tools.c.stable_key.in_(_skill_keys()))
        .distinct()
    ).scalars()

    for workspace_id in workspace_ids:
        for skill_name, *_ in _skill_definitions():
            desired_tool, desired_version, _ = _desired(skill_name, workspace_id)
            current_version_id = bind.scalar(
                sa.select(tools.c.current_version_id).where(
                    tools.c.workspace_id == workspace_id,
                    tools.c.id == desired_tool.id,
                )
            )
            if current_version_id is None:
                continue
            _assert_downgrade_safe(
                bind,
                desired_tool.id,
                current_version_id,
                tables,
            )
            bind.execute(
                tools.update()
                .where(
                    tools.c.workspace_id == workspace_id,
                    tools.c.id == desired_tool.id,
                )
                .values(current_version_id=None)
            )
            bind.execute(
                policies.delete().where(
                    policies.c.workspace_id == workspace_id,
                    policies.c.tool_id == desired_tool.id,
                )
            )
            bind.execute(
                versions.delete().where(
                    versions.c.workspace_id == workspace_id,
                    versions.c.tool_id == desired_tool.id,
                )
            )
            if permissions is not None:
                bind.execute(
                    permissions.delete().where(
                        permissions.c.workspace_id == workspace_id,
                        permissions.c.resource_type == "tool",
                        permissions.c.resource_id == desired_tool.id,
                    )
                )
            bind.execute(
                tools.delete().where(
                    tools.c.workspace_id == workspace_id,
                    tools.c.id == desired_tool.id,
                )
            )


def _skill_definitions():
    from app.shareddomain.tools.catalog import BUILTIN_SKILL_DEFINITIONS

    return BUILTIN_SKILL_DEFINITIONS


def _skill_keys() -> tuple[str, ...]:
    return tuple(f"skill_{item[0]}" for item in _skill_definitions())
