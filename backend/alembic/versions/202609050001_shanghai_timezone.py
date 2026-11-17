"""Use Shanghai time for user-facing and business calendar behavior."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op
from app.domain.tools.catalog.service import (
    canonical_definition_hash,
    stable_catalog_id,
)
from app.entities.defaults import utc_now
from app.entities.tools import Tool, ToolPolicy, ToolSource, ToolVersion

revision: str = "202609050001"
down_revision: str | None = "202609040001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Fix governance settings and refresh the built-in current-time tool."""
    bind = op.get_bind()
    op.execute(
        sa.text(
            "UPDATE workspace_governance "
            "SET timezone = 'Asia/Shanghai' "
            "WHERE timezone <> 'Asia/Shanghai'"
        )
    )
    op.alter_column(
        "workspace_governance",
        "timezone",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        server_default="Asia/Shanghai",
    )

    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    bindings = sa.Table("application_tool_bindings", metadata, autoload_with=bind)
    workspace_ids = bind.execute(
        sa.select(tools.c.workspace_id).where(
            tools.c.stable_key == "current_time"
        )
    ).scalars()
    timestamp = datetime.now(UTC)

    for workspace_id in workspace_ids:
        catalog = build_workspace_system_catalog(workspace_id, timestamp)
        version = catalog.version
        if bind.scalar(
            sa.select(versions.c.id).where(versions.c.id == version.id)
        ) is None:
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
            .values(current_version_id=version.id, updated_at=timestamp)
        )
        bind.execute(
            policies.update()
            .where(policies.c.tool_id == catalog.tool.id)
            .values(
                tool_version_id=version.id,
                definition_hash=version.definition_hash,
                revision=policies.c.revision + 1,
                updated_at=timestamp,
            )
        )
        bind.execute(
            bindings.update()
            .where(bindings.c.tool_id == catalog.tool.id)
            .values(tool_version_id=version.id)
        )


def downgrade() -> None:
    """Restore the legacy governance default and retain immutable tool history."""
    op.execute(sa.text("UPDATE workspace_governance SET timezone = 'UTC'"))
    op.alter_column(
        "workspace_governance",
        "timezone",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        server_default="UTC",
    )


# Frozen definitions required to replay this historical migration.
CURRENT_TIME_TOOL_CODE = (
    "from datetime import datetime, timedelta, timezone\n"
    "result = {'iso8601': datetime.now(timezone(timedelta(hours=8))).isoformat()}\n"
)


@dataclass(frozen=True)
class WorkspaceSystemCatalog:
    sources: tuple[ToolSource, ToolSource]
    tool: Tool
    version: ToolVersion
    policy: ToolPolicy


def build_workspace_system_catalog(
    workspace_id: str,
    created_at: datetime | None = None,
) -> WorkspaceSystemCatalog:
    timestamp = created_at or utc_now()
    builtin_source_id = stable_catalog_id(f"source:{workspace_id}:builtin")
    python_source_id = stable_catalog_id(f"source:{workspace_id}:python")
    # The id key predates the Python move; ids are opaque hashes and renaming
    # the key would cascade a primary-key rewrite across tool tables.
    tool_id = stable_catalog_id(f"tool:{workspace_id}:builtin:current_time")
    input_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "iso8601": {"type": "string", "maxLength": 64},
        },
        "required": ["iso8601"],
        "additionalProperties": False,
    }
    execution_spec = {"code": CURRENT_TIME_TOOL_CODE}
    definition_hash = canonical_definition_hash(
        {
            "name": "current_time",
            "description": "Return the current time.",
            "input_schema": input_schema,
            "output_schema": output_schema,
            "execution_spec": execution_spec,
        }
    )
    version_id = stable_catalog_id(f"version:{tool_id}:{definition_hash}")
    return WorkspaceSystemCatalog(
        sources=(
            ToolSource(
                id=builtin_source_id,
                workspace_id=workspace_id,
                kind="builtin",
                name="Built-in",
                created_at=timestamp,
                updated_at=timestamp,
            ),
            ToolSource(
                id=python_source_id,
                workspace_id=workspace_id,
                kind="python",
                name="Python",
                created_at=timestamp,
                updated_at=timestamp,
            ),
        ),
        tool=Tool(
            id=tool_id,
            workspace_id=workspace_id,
            source_id=python_source_id,
            kind="python",
            stable_key="current_time",
            function_name="current_time",
            current_version_id=version_id,
            status="active",
            availability="available",
            created_at=timestamp,
            updated_at=timestamp,
        ),
        version=ToolVersion(
            id=version_id,
            workspace_id=workspace_id,
            tool_id=tool_id,
            revision=1,
            display_name="Current time",
            description="Return the current time.",
            input_schema=input_schema,
            output_schema=output_schema,
            execution_spec=execution_spec,
            definition_hash=definition_hash,
            created_at=timestamp,
        ),
        policy=ToolPolicy(
            id=stable_catalog_id(f"policy:{tool_id}"),
            workspace_id=workspace_id,
            tool_id=tool_id,
            tool_version_id=version_id,
            definition_hash=definition_hash,
            revision=1,
            approval="auto",
            effect="pure",
            allowed_access_sources=["console", "public", "api"],
            workflow_callable=True,
            parallel_safe=False,
            created_at=timestamp,
            updated_at=timestamp,
        ),
    )
