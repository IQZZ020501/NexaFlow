"""Enable managed Skill selection for the built-in Python runtimes."""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op
from app.domain.tools.catalog.service import (
    canonical_definition_hash,
    stable_catalog_id,
)
from app.entities.defaults import utc_now
from app.entities.tools import Tool, ToolPolicy, ToolVersion

revision: str = "202608290001"
down_revision: str | None = "202608250007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _desired(stable_key: str, workspace_id: str):
    from app.domain.tools.catalog.service import (
        build_artifact_tool,
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


# Frozen definition required to replay this historical migration.
def build_inline_python_tool(
    workspace_id: str,
    created_at: datetime | None = None,
) -> tuple[Tool, ToolVersion, ToolPolicy]:
    timestamp = created_at or utc_now()
    source_id = stable_catalog_id(f"source:{workspace_id}:builtin")
    tool_id = stable_catalog_id(f"tool:{workspace_id}:builtin:inline_python")
    input_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "maxLength": 8192},
            "inputs": {"type": "object"},
            "skills": {
                "type": "array",
                "items": {
                    "type": "string",
                    "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$",
                },
                "maxItems": 8,
                "uniqueItems": True,
                "description": (
                    "Optional managed Skills to stage for this run. Each Skill "
                    "must be installed by the Worker."
                ),
            },
        },
        "required": ["code", "inputs"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {"result": {}},
        "required": ["result"],
        "additionalProperties": False,
    }
    execution_spec = {
        "builtin": "inline_python",
        "workflow_only": True,
        "direct_only": True,
    }
    definition_hash = canonical_definition_hash(
        {
            "name": "inline_python",
            "description": (
                "Run inline Python in the Workflow sandbox. Optional managed "
                "Skills are staged read-only and may install their requirements "
                "through the Worker public egress proxy."
            ),
            "input_schema": input_schema,
            "output_schema": output_schema,
            "execution_spec": execution_spec,
        }
    )
    version_id = stable_catalog_id(f"version:{tool_id}:{definition_hash}")
    return (
        Tool(
            id=tool_id,
            workspace_id=workspace_id,
            source_id=source_id,
            kind="builtin",
            stable_key="inline_python",
            function_name="inline_python",
            current_version_id=version_id,
            status="active",
            availability="available",
            created_at=timestamp,
            updated_at=timestamp,
        ),
        ToolVersion(
            id=version_id,
            workspace_id=workspace_id,
            tool_id=tool_id,
            revision=1,
            display_name="Python code",
            description=(
                "Run inline Python in the Workflow sandbox. Optional managed "
                "Skills are staged read-only and may install their requirements "
                "through the Worker public egress proxy."
            ),
            input_schema=input_schema,
            output_schema=output_schema,
            execution_spec=execution_spec,
            definition_hash=definition_hash,
            created_at=timestamp,
        ),
        ToolPolicy(
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
