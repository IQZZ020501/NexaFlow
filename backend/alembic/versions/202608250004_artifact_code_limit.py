"""Allow Artifact Tool code up to the sandbox limit."""

from collections.abc import Sequence
from datetime import UTC, datetime
import hashlib
import json
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "202608250004"
down_revision: str | None = "202608250003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_ID_NAMESPACE = UUID("2df58f89-2f5c-4e2b-9545-d50fb806a6db")


def _stable_catalog_id(key: str) -> str:
    return str(uuid5(_CATALOG_ID_NAMESPACE, key))


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    bindings = sa.Table("application_tool_bindings", metadata, autoload_with=bind)
    timestamp = datetime.now(UTC)

    rows = bind.execute(
        sa.select(tools.c.id, tools.c.workspace_id).where(
            tools.c.stable_key == "python_artifact",
            tools.c.kind == "builtin",
        )
    ).all()
    for tool_id, workspace_id in rows:
        current_version_id = bind.scalar(
            sa.select(tools.c.current_version_id).where(
                tools.c.workspace_id == workspace_id,
                tools.c.id == tool_id,
            )
        )
        current = bind.execute(
            sa.select(
                versions.c.id,
                versions.c.revision,
                versions.c.input_schema,
                versions.c.output_schema,
                versions.c.description,
            ).where(
                versions.c.workspace_id == workspace_id,
                versions.c.tool_id == tool_id,
                versions.c.id == current_version_id,
            )
        ).first()
        if current is None:
            continue
        input_schema = json.loads(json.dumps(current.input_schema))
        code_schema = input_schema.get("properties", {}).get("code")
        if not isinstance(code_schema, dict) or code_schema.get("maxLength", 0) >= 262144:
            continue
        code_schema["maxLength"] = 262144
        definition = {
            "name": "create_artifact",
            "description": current.description,
            "input_schema": input_schema,
            "output_schema": current.output_schema,
            "execution_spec": {"builtin": "python_artifact"},
        }
        definition_hash = hashlib.sha256(
            json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        version_id = _stable_catalog_id(f"version:{tool_id}:{definition_hash}")
        if bind.scalar(sa.select(versions.c.id).where(versions.c.id == version_id)) is None:
            bind.execute(
                versions.insert().values(
                    id=version_id,
                    workspace_id=workspace_id,
                    tool_id=tool_id,
                    revision=current.revision + 1,
                    display_name="Create downloadable file",
                    description=current.description,
                    input_schema=input_schema,
                    output_schema=definition["output_schema"],
                    execution_spec={"builtin": "python_artifact"},
                    definition_hash=definition_hash,
                    created_by_user_id=None,
                    created_at=timestamp,
                )
            )
        bind.execute(
            policies.update()
            .where(policies.c.workspace_id == workspace_id, policies.c.tool_id == tool_id)
            .values(
                tool_version_id=version_id,
                definition_hash=definition_hash,
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


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    bindings = sa.Table("application_tool_bindings", metadata, autoload_with=bind)
    rows = bind.execute(
        sa.select(tools.c.id, tools.c.workspace_id).where(
            tools.c.stable_key == "python_artifact",
            tools.c.kind == "builtin",
        )
    ).all()
    for tool_id, workspace_id in rows:
        prior = bind.execute(
            sa.select(versions.c.id, versions.c.definition_hash).where(
                versions.c.workspace_id == workspace_id,
                versions.c.tool_id == tool_id,
                versions.c.input_schema["properties"]["code"]["maxLength"].as_integer()
                == 32768,
            ).order_by(versions.c.revision.desc())
        ).first()
        if prior is None:
            continue
        bind.execute(
            policies.update()
            .where(policies.c.workspace_id == workspace_id, policies.c.tool_id == tool_id)
            .values(tool_version_id=prior.id, definition_hash=prior.definition_hash)
        )
        bind.execute(
            bindings.update()
            .where(bindings.c.workspace_id == workspace_id, bindings.c.tool_id == tool_id)
            .values(tool_version_id=prior.id)
        )
        bind.execute(
            tools.update()
            .where(tools.c.workspace_id == workspace_id, tools.c.id == tool_id)
            .values(current_version_id=prior.id)
        )
