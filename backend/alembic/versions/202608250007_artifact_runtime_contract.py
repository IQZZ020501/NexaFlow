"""Publish the exact installed Artifact runtime contract."""

from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "202608250007"
down_revision: str | None = "202608250006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
_CATALOG_ID_NAMESPACE = UUID("2df58f89-2f5c-4e2b-9545-d50fb806a6db")


def _stable_catalog_id(key: str) -> str:
    return str(uuid5(_CATALOG_ID_NAMESPACE, key))


def _contains_tool_version(value: object, tool_id: str, version_id: str) -> bool:
    if isinstance(value, dict):
        if value.get("tool_id") == tool_id and (
            value.get("version_id") == version_id
            or value.get("tool_version_id") == version_id
        ):
            return True
        return any(
            _contains_tool_version(item, tool_id, version_id)
            for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_tool_version(item, tool_id, version_id) for item in value)
    return False


def _assert_downgrade_safe(
    bind: sa.Connection,
    tool_id: str,
    version_id: str,
) -> None:
    inspector = sa.inspect(bind)
    if inspector.has_table("tool_invocations"):
        invocations = sa.Table("tool_invocations", sa.MetaData(), autoload_with=bind)
        if bind.scalar(
            sa.select(sa.literal(True))
            .where(
                invocations.c.tool_id == tool_id,
                invocations.c.tool_version_id == version_id,
            )
            .limit(1)
        ):
            raise RuntimeError(
                "Cannot downgrade while the current Artifact Tool contract is "
                "referenced by durable execution state."
            )
    for table_name, column_name in (
        ("agent_publication_versions", "resource_snapshot"),
        ("agent_run_snapshots", "tool_snapshots"),
        ("workflow_versions", "resource_snapshot"),
        ("workflow_run_details", "resource_snapshot"),
        ("tool_invocations", "policy_snapshot"),
    ):
        if not inspector.has_table(table_name):
            continue
        table = sa.Table(table_name, sa.MetaData(), autoload_with=bind)
        if any(
            _contains_tool_version(value, tool_id, version_id)
            for value in bind.execute(sa.select(table.c[column_name])).scalars()
        ):
            raise RuntimeError(
                "Cannot downgrade while the current Artifact Tool contract is "
                "referenced by durable execution state."
            )


_DESCRIPTION = (
    "Create or rewrite a downloadable file of any common type. Choose the exact "
    "filename; its extension determines the file type, and extensionless names "
    "are supported. For plain-text and source-code files, put the exact final "
    "file contents in content; they are saved without being executed. For DOCX, "
    "PDF, XLSX, PPTX, images, and other rich or binary formats, put a Python "
    "generator program in content and write the final file only to the provided "
    "global output_path; never use /tmp, the current directory, or a hard-coded "
    "path. Use only these installed libraries and import names: DOCX uses "
    "python-docx (`from docx import Document`); PDF uses PyMuPDF "
    "(`import pymupdf`, never reportlab); XLSX uses openpyxl; PPTX uses "
    "python-pptx (`from pptx import Presentation`); images use Pillow "
    "(`from PIL import Image`). Do not probe the environment, install packages, "
    "or create diagnostic files. The Python standard library is also available. User "
    "attachment text is already included in the conversation and can be used "
    "to produce an edited copy. Enforce requested measurable constraints in "
    "the generator before saving, and print concise validation results to stdout. "
    "The returned metadata includes stdout. Include the returned download_url "
    "verbatim in the final answer."
)
_CONTENT_DESCRIPTION = (
    "Exact UTF-8 contents for plain-text/source files, or Python generator "
    "code for rich/binary output that writes to output_path. For PDF import "
    "pymupdf; reportlab is unavailable."
)


def _definition(
    input_schema: dict,
    output_schema: dict,
    execution_spec: dict,
) -> tuple[str, dict, dict, dict, str]:
    input_schema = deepcopy(input_schema)
    output_schema = deepcopy(output_schema)
    execution_spec = deepcopy(execution_spec)
    content_schema = input_schema.get("properties", {}).get("content")
    if isinstance(content_schema, dict):
        content_schema["description"] = _CONTENT_DESCRIPTION
    return (
        _DESCRIPTION,
        input_schema,
        output_schema,
        execution_spec,
        hashlib.sha256(
            json.dumps(
                {
                    "name": "create_artifact",
                    "description": _DESCRIPTION,
                    "input_schema": input_schema,
                    "output_schema": output_schema,
                    "execution_spec": execution_spec,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    )


def _switch(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    tools = sa.Table("tools", metadata, autoload_with=bind)
    versions = sa.Table("tool_versions", metadata, autoload_with=bind)
    policies = sa.Table("tool_policies", metadata, autoload_with=bind)
    bindings = sa.Table("application_tool_bindings", metadata, autoload_with=bind)
    timestamp = datetime.now(UTC)
    rows = bind.execute(
        sa.select(tools.c.id, tools.c.workspace_id, tools.c.current_version_id).where(
            tools.c.stable_key == "artifact", tools.c.kind == "builtin"
        )
    ).all()
    for tool_id, workspace_id, current_version_id in rows:
        current = bind.execute(
            sa.select(
                versions.c.input_schema,
                versions.c.output_schema,
                versions.c.execution_spec,
            ).where(versions.c.id == current_version_id)
        ).first()
        if current is None:
            continue
        description, input_schema, output_schema, execution_spec, digest = _definition(
            current.input_schema,
            current.output_schema,
            current.execution_spec,
        )
        if downgrade:
            if current_version_id is not None:
                _assert_downgrade_safe(bind, tool_id, current_version_id)
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
            version_id, version_hash = previous
        else:
            version_id = _stable_catalog_id(f"version:{tool_id}:{digest}")
            version_hash = digest
            if bind.scalar(sa.select(versions.c.id).where(versions.c.id == version_id)) is None:
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
