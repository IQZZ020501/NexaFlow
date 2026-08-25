"""Allow the built-in Artifact Tool to create generic downloadable files."""

from collections.abc import Sequence
from datetime import UTC, datetime
import hashlib
import json
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "202608250001"
down_revision: str | None = "202608240002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_ID_NAMESPACE = UUID("2df58f89-2f5c-4e2b-9545-d50fb806a6db")


def _stable_catalog_id(key: str) -> str:
    return str(uuid5(_CATALOG_ID_NAMESPACE, key))


def _definition(*, generic: bool) -> tuple[str, str, dict, dict, dict, str]:
    if generic:
        display_name = "Create downloadable file"
        description = (
            "Create or rewrite a downloadable file of any common type. Choose the exact "
            "filename; its extension determines the file type, and extensionless names "
            "are supported. For plain-text and source-code files, put the exact final "
            "file contents in code; they are saved without being executed. For rich or "
            "binary formats, put Python generator code in code and write the final file "
            "to the global output_path in the isolated sandbox. python-docx, PyMuPDF, "
            "openpyxl, python-pptx, Pillow, and the Python standard library are "
            "available. User "
            "attachment text is already included in the conversation and can be used "
            "to produce an edited copy. Enforce requested measurable constraints in "
            "the code before saving, and print concise validation results to stdout. "
            "The returned metadata includes stdout. Include the returned download_url "
            "verbatim in the final answer."
        )
        input_schema = {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "maxLength": 32768,
                    "description": (
                        "Exact UTF-8 file contents for plain-text/source files, or Python "
                        "generator code that writes rich/binary output to output_path."
                    ),
                },
                "filename": {"type": "string", "maxLength": 120},
            },
            "required": ["code", "filename"],
            "additionalProperties": False,
        }
        format_length = 32
    else:
        display_name = "Create document or page"
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
        format_length = 10
    output_schema = {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "maxLength": 36},
            "format": {"type": "string", "maxLength": format_length},
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
    if generic:
        output_schema["properties"]["stdout"] = {
            "type": "string",
            "maxLength": 2000,
        }
        output_schema["required"].append("stdout")
    execution_spec = {"builtin": "python_artifact"}
    payload = {
        "name": "create_artifact",
        "description": description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "execution_spec": execution_spec,
    }
    definition_hash = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return (
        display_name,
        description,
        input_schema,
        output_schema,
        execution_spec,
        definition_hash,
    )


def _switch_tool_version(*, generic: bool) -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    bindings = sa.Table("application_tool_bindings", metadata, autoload_with=bind)
    (
        display_name,
        description,
        input_schema,
        output_schema,
        execution_spec,
        definition_hash,
    ) = _definition(generic=generic)
    timestamp = datetime.now(UTC)

    rows = bind.execute(
        sa.select(tools.c.id, tools.c.workspace_id).where(
            tools.c.stable_key == "python_artifact",
            tools.c.kind == "builtin",
        )
    ).all()
    for tool_id, workspace_id in rows:
        version_id = _stable_catalog_id(f"version:{tool_id}:{definition_hash}")
        version_exists = bind.scalar(
            sa.select(versions.c.id).where(versions.c.id == version_id)
        )
        if version_exists is None:
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
                    display_name=display_name,
                    description=description,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    execution_spec=execution_spec,
                    definition_hash=definition_hash,
                    created_by_user_id=None,
                    created_at=timestamp,
                )
            )

        policy_id = bind.scalar(
            sa.select(policies.c.id).where(
                policies.c.workspace_id == workspace_id,
                policies.c.tool_id == tool_id,
            )
        )
        if policy_id is None:
            raise RuntimeError("python_artifact Tool policy is missing")
        bind.execute(
            bindings.update()
            .where(
                bindings.c.workspace_id == workspace_id,
                bindings.c.tool_id == tool_id,
            )
            .values(tool_version_id=version_id)
        )
        bind.execute(
            policies.update()
            .where(policies.c.id == policy_id)
            .values(
                tool_version_id=version_id,
                definition_hash=definition_hash,
                revision=policies.c.revision + 1,
                updated_at=timestamp,
            )
        )
        bind.execute(
            tools.update()
            .where(tools.c.id == tool_id)
            .values(current_version_id=version_id, updated_at=timestamp)
        )


def upgrade() -> None:
    op.drop_constraint(
        "ck_generated_artifacts_format",
        "generated_artifacts",
        type_="check",
    )
    op.alter_column(
        "generated_artifacts",
        "format",
        existing_type=sa.String(length=10),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_generated_artifacts_format",
        "generated_artifacts",
        "length(format) BETWEEN 1 AND 32",
    )
    _switch_tool_version(generic=True)


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    artifacts = sa.Table("generated_artifacts", metadata, autoload_with=bind)
    unsupported = bind.scalar(
        sa.select(sa.func.count()).where(
            artifacts.c.format.not_in(("docx", "html"))
        )
    )
    if unsupported:
        raise RuntimeError(
            "Cannot downgrade while generic generated artifacts still exist."
        )

    _switch_tool_version(generic=False)
    op.drop_constraint(
        "ck_generated_artifacts_format",
        "generated_artifacts",
        type_="check",
    )
    op.alter_column(
        "generated_artifacts",
        "format",
        existing_type=sa.String(length=32),
        type_=sa.String(length=10),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_generated_artifacts_format",
        "generated_artifacts",
        "format IN ('docx', 'html')",
    )
