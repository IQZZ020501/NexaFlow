"""Add generated artifacts and their built-in Tool."""

from collections.abc import Sequence
from datetime import UTC, datetime
import hashlib
import json
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "202608240002"
down_revision: str | None = "202608240001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_ID_NAMESPACE = UUID("2df58f89-2f5c-4e2b-9545-d50fb806a6db")


def _stable_catalog_id(key: str) -> str:
    return str(uuid5(_CATALOG_ID_NAMESPACE, key))


def _definition() -> tuple[str, dict, dict, dict, str]:
    description = (
        "Create a DOCX or self-contained static HTML file by running Python in "
        "the isolated sandbox. Write the final file to the global output_path. "
        "python-docx is available for DOCX files. HTML must use inline CSS and "
        "must not use JavaScript or external resources. Requested administrator "
        "Skills are readable below the global skills_dir. Include the returned "
        "download_url verbatim in the final answer."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "maxLength": 32768},
            "format": {
                "type": "string",
                "enum": ["docx", "html"],
                "maxLength": 10,
            },
            "filename": {"type": "string", "maxLength": 120},
            "skills": {
                "type": "array",
                "items": {"type": "string", "maxLength": 64},
                "maxItems": 8,
            },
        },
        "required": ["code", "format", "filename"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "maxLength": 36},
            "format": {"type": "string", "maxLength": 10},
            "filename": {"type": "string", "maxLength": 120},
            "download_url": {"type": "string", "maxLength": 4096},
            "expires_at": {"type": "string", "maxLength": 64},
            "size_bytes": {"type": "integer"},
        },
        "required": [
            "artifact_id",
            "format",
            "filename",
            "download_url",
            "expires_at",
            "size_bytes",
        ],
        "additionalProperties": False,
    }
    execution_spec = {"builtin": "python_artifact"}
    payload = {
        "name": "create_artifact",
        "description": description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "execution_spec": execution_spec,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return description, input_schema, output_schema, execution_spec, digest


def _backfill_tool() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    workspaces = sa.Table("workspaces", metadata, autoload_with=bind)
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    (
        description,
        input_schema,
        output_schema,
        execution_spec,
        definition_hash,
    ) = _definition()
    timestamp = datetime.now(UTC)

    for workspace_id in bind.execute(sa.select(workspaces.c.id)).scalars():
        source_id = _stable_catalog_id(f"source:{workspace_id}:builtin")
        tool_id = _stable_catalog_id(
            f"tool:{workspace_id}:builtin:python_artifact"
        )
        version_id = _stable_catalog_id(f"version:{tool_id}:{definition_hash}")
        bind.execute(
            tools.insert().values(
                id=tool_id,
                workspace_id=workspace_id,
                source_id=source_id,
                kind="builtin",
                stable_key="python_artifact",
                function_name="create_artifact",
                current_version_id=None,
                status="active",
                availability="available",
                created_by_user_id=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        bind.execute(
            versions.insert().values(
                id=version_id,
                workspace_id=workspace_id,
                tool_id=tool_id,
                revision=1,
                display_name="Create document or page",
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                execution_spec=execution_spec,
                definition_hash=definition_hash,
                created_by_user_id=None,
                created_at=timestamp,
            )
        )
        bind.execute(
            policies.insert().values(
                id=_stable_catalog_id(f"policy:{tool_id}"),
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
                reviewed_by_user_id=None,
                reviewed_at=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        bind.execute(
            tools.update()
            .where(tools.c.id == tool_id)
            .values(current_version_id=version_id)
        )


def upgrade() -> None:
    op.create_table(
        "generated_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("filename", sa.String(length=120), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "format IN ('docx', 'html')",
            name="ck_generated_artifacts_format",
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 5242880",
            name="ck_generated_artifacts_size",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_generated_artifacts_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_generated_artifacts_workspace_id"),
        "generated_artifacts",
        ["workspace_id"],
    )
    op.create_index(
        op.f("ix_generated_artifacts_run_id"),
        "generated_artifacts",
        ["run_id"],
    )
    op.create_index(
        op.f("ix_generated_artifacts_expires_at"),
        "generated_artifacts",
        ["expires_at"],
    )
    _backfill_tool()


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    workspaces = sa.Table("workspaces", metadata, autoload_with=bind)
    tools = sa.Table("tools", metadata, autoload_with=bind)
    tool_ids = [
        _stable_catalog_id(f"tool:{workspace_id}:builtin:python_artifact")
        for workspace_id in bind.execute(sa.select(workspaces.c.id)).scalars()
    ]
    if tool_ids:
        bind.execute(tools.delete().where(tools.c.id.in_(tool_ids)))
    op.drop_index(
        op.f("ix_generated_artifacts_expires_at"),
        table_name="generated_artifacts",
    )
    op.drop_index(
        op.f("ix_generated_artifacts_run_id"),
        table_name="generated_artifacts",
    )
    op.drop_index(
        op.f("ix_generated_artifacts_workspace_id"),
        table_name="generated_artifacts",
    )
    op.drop_table("generated_artifacts")
