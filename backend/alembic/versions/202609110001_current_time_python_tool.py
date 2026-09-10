"""Move the built-in Current time Tool to the Python source.

The Current time system Tool is reimplemented as workspace Python code that
runs in the Workflow sandbox, so its catalog kind and source move from
Built-in to Python. Existing workspaces are reconciled from the current
system catalog builder, matching the seed-migration refresh pattern; pinned
tool snapshots inside published Agent/Workflow versions keep their immutable
history and must be republished to pick up the new definition.
"""

from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision: str = "202609110001"
down_revision: str | None = "202609100001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _catalog_tables(
    bind: sa.Connection,
) -> tuple[sa.Table, sa.Table, sa.Table, sa.Table]:
    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    bindings = sa.Table("application_tool_bindings", metadata, autoload_with=bind)
    return tools, versions, policies, bindings


def _apply(bind: sa.Connection) -> None:
    """Reconcile every workspace's Current time Tool to the Python definition."""
    from app.domain.tools.catalog.service import build_workspace_system_catalog

    tools, versions, policies, bindings = _catalog_tables(bind)
    timestamp = datetime.now(UTC)
    workspace_ids = bind.execute(
        sa.select(tools.c.workspace_id).where(tools.c.stable_key == "current_time")
    ).scalars()
    for workspace_id in workspace_ids:
        catalog = build_workspace_system_catalog(workspace_id, timestamp)
        version = catalog.version
        if (
            bind.scalar(
                sa.select(versions.c.id).where(versions.c.id == version.id)
            )
            is None
        ):
            revision_no = bind.execute(
                sa.select(
                    sa.func.coalesce(sa.func.max(versions.c.revision), 0) + 1
                ).where(versions.c.tool_id == catalog.tool.id)
            ).scalar_one()
            bind.execute(
                versions.insert().values(
                    **asdict(replace(version, revision=revision_no))
                )
            )
        bind.execute(
            tools.update()
            .where(tools.c.id == catalog.tool.id)
            .values(
                source_id=catalog.tool.source_id,
                kind=catalog.tool.kind,
                current_version_id=version.id,
                updated_at=timestamp,
            )
        )
        bind.execute(
            policies.update()
            .where(policies.c.tool_id == catalog.tool.id)
            .values(
                tool_version_id=version.id,
                definition_hash=version.definition_hash,
                parallel_safe=catalog.policy.parallel_safe,
                revision=policies.c.revision + 1,
                updated_at=timestamp,
            )
        )
        bind.execute(
            bindings.update()
            .where(bindings.c.tool_id == catalog.tool.id)
            .values(tool_version_id=version.id)
        )


def _legacy_version_id(
    bind: sa.Connection,
    versions: sa.Table,
    tool_id: str,
    workspace_id: str,
) -> tuple[str | None, str]:
    """Locate the pre-Python version row that upgrade left in place.

    Workspaces seeded by the 202608160003 migration and workspaces created
    through the live catalog builder used different descriptions, so both
    legacy definition hashes are candidates.
    """
    from app.domain.tools.catalog.service import canonical_definition_hash, stable_catalog_id

    input_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {"iso8601": {"type": "string", "maxLength": 64}},
        "required": ["iso8601"],
        "additionalProperties": False,
    }
    execution_spec = {"builtin": "current_time"}
    candidates = []
    for description in ("Return the current time.", "Return the current UTC time."):
        definition_hash = canonical_definition_hash(
            {
                "name": "current_time",
                "description": description,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "execution_spec": execution_spec,
            }
        )
        candidates.append(
            (
                stable_catalog_id(f"version:{tool_id}:{definition_hash}"),
                definition_hash,
            )
        )
    for version_id, definition_hash in candidates:
        if (
            bind.scalar(
                sa.select(versions.c.id).where(
                    versions.c.id == version_id,
                    versions.c.workspace_id == workspace_id,
                )
            )
            is not None
        ):
            return version_id, definition_hash
    return None, ""


def _revert(bind: sa.Connection) -> None:
    """Restore the Built-in definition while retaining immutable tool history."""
    from app.domain.tools.catalog.service import stable_catalog_id

    tools, versions, policies, bindings = _catalog_tables(bind)
    timestamp = datetime.now(UTC)
    rows = bind.execute(
        sa.select(tools.c.id, tools.c.workspace_id).where(
            tools.c.stable_key == "current_time"
        )
    )
    for tool_id, workspace_id in rows:
        legacy_version_id, legacy_hash = _legacy_version_id(
            bind, versions, tool_id, workspace_id
        )
        if legacy_version_id is None:
            continue
        bind.execute(
            tools.update()
            .where(tools.c.id == tool_id)
            .values(
                source_id=stable_catalog_id(f"source:{workspace_id}:builtin"),
                kind="builtin",
                current_version_id=legacy_version_id,
                updated_at=timestamp,
            )
        )
        bind.execute(
            policies.update()
            .where(policies.c.tool_id == tool_id)
            .values(
                tool_version_id=legacy_version_id,
                definition_hash=legacy_hash,
                parallel_safe=True,
                revision=policies.c.revision + 1,
                updated_at=timestamp,
            )
        )
        bind.execute(
            bindings.update()
            .where(bindings.c.tool_id == tool_id)
            .values(tool_version_id=legacy_version_id)
        )


def upgrade() -> None:
    _apply(op.get_bind())


def downgrade() -> None:
    _revert(op.get_bind())
