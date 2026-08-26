"""Restore rich generator semantics for the generic Artifact tool."""

from collections.abc import Sequence
from datetime import UTC, datetime
import hashlib
import json
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "202608250006"
down_revision: str | None = "202608250005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
_CATALOG_ID_NAMESPACE = UUID("2df58f89-2f5c-4e2b-9545-d50fb806a6db")


def _stable_catalog_id(key: str) -> str:
    return str(uuid5(_CATALOG_ID_NAMESPACE, key))


def _definition() -> tuple[str, dict, dict, dict, str]:
    description = (
        "Create or rewrite a downloadable file of any common type. Choose the exact "
        "filename; its extension determines the file type, and extensionless names "
        "are supported. For plain-text and source-code files, put the exact final "
        "file contents in content; they are saved without being executed. For DOCX, "
        "PDF, XLSX, PPTX, images, and other rich or binary formats, put a Python "
        "generator program in content and write the final file only to the provided "
        "global output_path; never use /tmp, the current directory, or a hard-coded "
        "path. The isolated file runtime provides common document, spreadsheet, "
        "presentation, image, and PDF libraries, along with the Python standard "
        "library. User attachment text is already included in the conversation and "
        "can be used to produce an edited copy. Enforce requested measurable "
        "constraints in the generator before saving, and print concise validation "
        "results to stdout. The returned metadata includes stdout. Include the "
        "returned download_url verbatim in the final answer."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "maxLength": 262144,
                "description": (
                    "Exact UTF-8 contents for plain-text/source files, or Python "
                    "generator code for rich/binary output that writes to output_path."
                ),
            },
            "content_mode": {
                "type": "string",
                "enum": ["text", "python"],
                "description": (
                    "Use text for final plain-text contents or python for generator "
                    "code. Omit only when the filename makes the mode unambiguous."
                ),
            },
            "filename": {"type": "string", "maxLength": 120},
        },
        "required": ["content", "filename"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "maxLength": 36},
            "format": {"type": "string", "maxLength": 32},
            "filename": {"type": "string", "maxLength": 120},
            "download_url": {"type": "string", "maxLength": 4096},
            "expires_at": {"type": "string", "maxLength": 64},
            "size_bytes": {"type": "integer"},
            "stdout": {"type": "string", "maxLength": 2000},
            "artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string", "maxLength": 36},
                        "format": {"type": "string", "maxLength": 32},
                        "filename": {"type": "string", "maxLength": 120},
                        "mime_type": {"type": "string", "maxLength": 120},
                        "download_url": {"type": "string", "maxLength": 4096},
                        "expires_at": {"type": "string", "maxLength": 64},
                        "size_bytes": {"type": "integer"},
                    },
                    "required": [
                        "artifact_id",
                        "format",
                        "filename",
                        "mime_type",
                        "download_url",
                        "expires_at",
                        "size_bytes",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "artifact_id",
            "format",
            "filename",
            "download_url",
            "expires_at",
            "size_bytes",
            "stdout",
            "artifacts",
        ],
        "additionalProperties": False,
    }
    execution_spec = {"builtin": "artifact"}
    payload = {
        "name": "create_artifact",
        "description": description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "execution_spec": execution_spec,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return description, input_schema, output_schema, execution_spec, digest


def _switch(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    bindings = sa.Table("application_tool_bindings", metadata, autoload_with=bind)
    description, input_schema, output_schema, execution_spec, digest = _definition()
    timestamp = datetime.now(UTC)
    rows = bind.execute(
        sa.select(tools.c.id, tools.c.workspace_id).where(
            tools.c.stable_key == "artifact", tools.c.kind == "builtin"
        )
    ).all()
    for tool_id, workspace_id in rows:
        if downgrade:
            previous = bind.execute(
                sa.select(versions.c.id, versions.c.definition_hash)
                .where(
                    versions.c.workspace_id == workspace_id,
                    versions.c.tool_id == tool_id,
                    versions.c.definition_hash != digest,
                )
                .order_by(versions.c.revision.desc())
            ).first()
            if previous is None:
                continue
            previous_id, previous_hash = previous
            bind.execute(
                policies.update()
                .where(
                    policies.c.workspace_id == workspace_id,
                    policies.c.tool_id == tool_id,
                )
                .values(
                    tool_version_id=previous_id,
                    definition_hash=previous_hash,
                    revision=policies.c.revision + 1,
                    updated_at=timestamp,
                )
            )
            bind.execute(
                bindings.update()
                .where(
                    bindings.c.workspace_id == workspace_id,
                    bindings.c.tool_id == tool_id,
                )
                .values(tool_version_id=previous_id)
            )
            bind.execute(
                tools.update()
                .where(
                    tools.c.workspace_id == workspace_id,
                    tools.c.id == tool_id,
                )
                .values(current_version_id=previous_id, updated_at=timestamp)
            )
            continue
        version_id = _stable_catalog_id(f"version:{tool_id}:{digest}")
        if (
            bind.scalar(sa.select(versions.c.id).where(versions.c.id == version_id))
            is None
        ):
            revision_number = (
                bind.scalar(
                    sa.select(sa.func.max(versions.c.revision)).where(
                        versions.c.tool_id == tool_id
                    )
                )
                or 0
            ) + 1
            bind.execute(
                versions.insert().values(
                    id=version_id,
                    workspace_id=workspace_id,
                    tool_id=tool_id,
                    revision=revision_number,
                    display_name="Create downloadable file",
                    description=description,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    execution_spec=execution_spec,
                    definition_hash=digest,
                    created_by_user_id=None,
                    created_at=timestamp,
                )
            )
        bind.execute(
            policies.update()
            .where(policies.c.workspace_id == workspace_id, policies.c.tool_id == tool_id)
            .values(
                tool_version_id=version_id,
                definition_hash=digest,
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
