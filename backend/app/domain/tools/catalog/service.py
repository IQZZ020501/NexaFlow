import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from fastapi import HTTPException, status
from mcp.types import Tool as McpTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tools.access.permissions import (
    ToolAuthorization,
    ToolPermissionLabel,
    evaluate_tool_authorization,
    has_tool_workspace_access,
    require_tool_view,
)
from app.domain.tools.catalog.guides import skill_instructions
from app.entities.defaults import utc_now
from app.entities.identity.user import User
from app.entities.tools import (
    Tool,
    ToolAccess,
    ToolPolicy,
    ToolSource,
    ToolVersion,
)

CATALOG_ID_NAMESPACE = UUID("2df58f89-2f5c-4e2b-9545-d50fb806a6db")

_SPREADSHEET_VALUE_GUIDANCE = (
    "For XLSX deliverables, follow the user's choice of stored values or formulas. "
    "When numeric amounts, totals or directly readable values are required, calculate "
    "them first and write actual numbers, not formula strings. Reopen the saved file "
    "with openpyxl data_only=True and verify those cells before delivery. openpyxl "
    "and the renderer do not calculate formulas. Preserve formulas when requested; "
    "inspection.details.uncached_formulas reports cells without a readable cached result. "
    "Review inspection warnings and correct any mismatch with the user's requirements."
)

BUILTIN_SKILL_DEFINITIONS = (
    (
        "documents",
        "documents_skill",
        "Documents Skill",
        (
            "Read, create or edit Word DOCX files with python-docx; preserve templates, sections, media, rich formatting and relevant package parts."
            " Call with {} to load the complete guide, then use authorized bash in the"
            " private sandbox. This call only loads instructions; it does not create a file."
            " Save requested deliverables under /workspace/outputs/ and return bash's download_url."
        ),
    ),
    (
        "pdf",
        "pdf_skill",
        "PDF Skill",
        (
            "Read, create, render, merge, split, rotate, redact or fill PDFs with PyMuPDF."
            " Call with {} to load the complete guide, then use authorized bash in the"
            " private sandbox. This call only loads instructions; it does not create a file."
            " Save requested deliverables under /workspace/outputs/ and return bash's download_url."
        ),
    ),
    (
        "pptx",
        "pptx_skill",
        "PPTX Skill",
        (
            "Read, design, create or revise PowerPoint with python-pptx. Choose layouts and palettes freely; preserve native charts, images, notes and templates during edits."
            " Call with {} to load the complete guide, then use authorized bash in the"
            " private sandbox. This call only loads instructions; it does not create a file."
            " Save requested deliverables under /workspace/outputs/ and return bash's download_url."
        ),
    ),
    (
        "spreadsheets",
        "spreadsheets_skill",
        "Spreadsheets Skill",
        (
            "Analyze CSV/Excel with pandas and edit XLSX/XLSM with openpyxl; preserve formulas, formatting, charts, validation, names and macro parts when supported."
            " Call with {} to load the complete guide, then use authorized bash in the"
            " private sandbox. This call only loads instructions; it does not create a file."
            " Save requested deliverables under /workspace/outputs/ and return bash's download_url."
        ),
    ),
    (
        "skill-creator",
        "skill_creator",
        "Skill Creator",
        (
            "Create or revise an importable NexaFlow SKILL.md/ZIP package with focused instructions and optional scripts, references and assets. This does not publish, bind or authorize a Skill."
            " Call with {} to load the complete guide, then use authorized bash in the"
            " private sandbox. This call only loads instructions; it does not create a file."
            " Save requested deliverables under /workspace/outputs/ and return bash's download_url."
        ),
    ),
)

INTERNAL_BUILTIN_FUNCTION_NAMES = (
    "bash",
    "create_artifact",
    "inline_python",
    "install_skill_dependencies",
)


def stable_catalog_id(key: str) -> str:
    return str(uuid5(CATALOG_ID_NAMESPACE, key))


def canonical_definition_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def mcp_definition_hash(definition: dict[str, Any]) -> str:
    normalized = normalize_mcp_definition(definition)
    return canonical_definition_hash(normalized)


def normalize_mcp_definition(definition: dict[str, Any]) -> dict[str, Any]:
    tool = McpTool(
        name=str(definition.get("name") or ""),
        description=str(definition.get("description") or ""),
        input_schema=(
            definition.get("input_schema")
            or definition.get("inputSchema")
            or {"type": "object"}
        ),
        annotations=definition.get("annotations"),
    )
    normalized = {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.input_schema,
        "annotations": (
            tool.annotations.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
            if tool.annotations is not None
            else None
        ),
    }
    if definition.get("long_task"):
        normalized["long_task"] = definition["long_task"]
    return normalized


def mcp_function_name_candidates(server_id: str, tool_name: str) -> tuple[str, ...]:
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_name).strip("_")[:40] or "tool"
    digest = hashlib.sha256(f"{server_id}:{tool_name}".encode()).hexdigest()
    candidates = tuple(
        f"mcp_{stem[: 59 - length]}_{digest[:length]}"
        for length in range(8, 57, 4)
    )
    return (*candidates, f"mcp_{digest[:60]}")


def mcp_function_name(server_id: str, tool_name: str) -> str:
    return mcp_function_name_candidates(server_id, tool_name)[0]


async def reconcile_mcp_discovery(
    db: AsyncSession,
    server: Any,
    source: ToolSource,
    discovery: list[dict[str, Any]],
) -> None:
    from app.infra.db.repositories.tools import repository
    from app.infra.db.repositories.workspaces import repository as workspace_repository

    await workspace_repository.lock_workspace(db, source.workspace_id)
    locked_source = await repository.lock_tool_source(
        db,
        source.workspace_id,
        source.id,
    )
    if locked_source is None or locked_source.mcp_server_id != server.id:
        raise ValueError("MCP Tool source is unavailable.")

    normalized = [normalize_mcp_definition(item) for item in discovery]
    names = [item["name"] for item in normalized]
    if len(names) != len(set(names)):
        raise ValueError("MCP discovery contains duplicate Tool names.")

    timestamp = utc_now()
    existing_tools = await repository.list_tools_by_source(
        db,
        source.workspace_id,
        source.id,
    )
    by_key = {tool.stable_key: tool for tool in existing_tools}
    discovered_names = set(names)
    for tool in existing_tools:
        if tool.stable_key not in discovered_names and tool.availability != "unavailable":
            tool.availability = "unavailable"
            tool.updated_at = timestamp
            await repository.save_tool(db, tool)

    for definition in normalized:
        tool_name = definition["name"]
        tool = by_key.get(tool_name)
        is_new_tool = tool is None
        if tool is None:
            function_name = ""
            for candidate in mcp_function_name_candidates(server.id, tool_name):
                if (
                    await repository.get_tool_by_function_name(
                        db,
                        source.workspace_id,
                        candidate,
                    )
                    is None
                ):
                    function_name = candidate
                    break
            if not function_name:
                raise ValueError("MCP Tool function name could not be allocated.")
            tool = await repository.save_tool(
                db,
                Tool(
                    workspace_id=source.workspace_id,
                    source_id=source.id,
                    kind="mcp",
                    stable_key=tool_name,
                    function_name=function_name,
                    current_version_id=None,
                    status="active",
                    availability="available",
                    created_by_user_id=locked_source.created_by_user_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                ),
            )
            by_key[tool_name] = tool

        definition_hash = canonical_definition_hash(definition)
        version = await repository.get_tool_version_by_hash(
            db,
            source.workspace_id,
            tool.id,
            definition_hash,
        )
        if version is None:
            versions = await repository.list_tool_versions(
                db,
                source.workspace_id,
                tool.id,
            )
            version = await repository.save_tool_version(
                db,
                ToolVersion(
                    workspace_id=source.workspace_id,
                    tool_id=tool.id,
                    revision=(versions[0].revision + 1) if versions else 1,
                    display_name=tool_name[:120],
                    description=definition["description"],
                    input_schema=definition["input_schema"],
                    output_schema=None,
                    execution_spec={
                        "server_id": server.id,
                        "tool_name": tool_name,
                        "annotations": definition["annotations"],
                        **({"long_task": definition["long_task"]} if definition.get("long_task") else {}),
                    },
                    definition_hash=definition_hash,
                    created_by_user_id=locked_source.created_by_user_id,
                    created_at=timestamp,
                ),
            )
        if is_new_tool:
            await repository.save_tool_policy(
                db,
                ToolPolicy(
                    workspace_id=source.workspace_id,
                    tool_id=tool.id,
                    tool_version_id=version.id,
                    definition_hash=definition_hash,
                    revision=1,
                    approval="each_call",
                    effect="unknown",
                    allowed_access_sources=["console"],
                    workflow_callable=True,
                    parallel_safe=False,
                    created_at=timestamp,
                    updated_at=timestamp,
                ),
            )
        tool.current_version_id = version.id
        tool.availability = "available"
        tool.updated_at = timestamp
        await repository.save_tool(db, tool)


@dataclass(frozen=True)
class ToolCatalogItem:
    tool: Tool
    source: ToolSource
    version: ToolVersion | None
    policy: ToolPolicy | None
    access: ToolAccess
    permission: ToolPermissionLabel | None


@dataclass(frozen=True)
class ToolCatalogDetail:
    tool: Tool
    source: ToolSource
    version: ToolVersion | None
    policy: ToolPolicy | None
    authorization: ToolAuthorization

    @property
    def access(self) -> ToolAccess:
        return self.authorization.access

    @property
    def permission(self) -> ToolPermissionLabel | None:
        return self.authorization.permission


@dataclass(frozen=True)
class McpCatalogLeaf:
    source: ToolSource
    tool: Tool
    version: ToolVersion
    policy: ToolPolicy | None


def mcp_catalog_leaf_definition(leaf: McpCatalogLeaf) -> McpTool:
    return McpTool(
        name=leaf.tool.stable_key,
        description=leaf.version.description,
        input_schema=leaf.version.input_schema,
        annotations=leaf.version.execution_spec.get("annotations"),
    )


def legacy_mcp_policy_mode(leaf: McpCatalogLeaf) -> str:
    if leaf.source.status != "active" or leaf.tool.status != "active":
        return "disabled"
    policy = leaf.policy
    if policy is not None and policy.approval == "disabled":
        return "disabled"
    if (
        policy is None
        or policy.tool_version_id != leaf.version.id
        or policy.definition_hash != leaf.version.definition_hash
    ):
        return "approval_required"
    if policy.approval == "auto" and policy.effect == "external_read":
        return "read_only"
    return "approval_required"


async def list_mcp_catalog_leaves(
    db: AsyncSession,
    workspace_id: str,
    mcp_server_id: str,
    *,
    available_only: bool = False,
) -> list[McpCatalogLeaf]:
    from app.infra.db.repositories.tools import repository

    return [
        McpCatalogLeaf(source=source, tool=tool, version=version, policy=policy)
        for source, tool, version, policy in await repository.list_mcp_catalog_rows(
            db,
            workspace_id,
            mcp_server_id,
            available_only=available_only,
        )
    ]


async def get_mcp_catalog_leaf(
    db: AsyncSession,
    workspace_id: str,
    mcp_server_id: str,
    tool_name: str,
) -> McpCatalogLeaf | None:
    leaves = await list_mcp_catalog_leaves(db, workspace_id, mcp_server_id)
    return next((leaf for leaf in leaves if leaf.tool.stable_key == tool_name), None)


async def list_tool_catalog(
    db: AsyncSession,
    workspace_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int | None = None,
    offset: int = 0,
) -> list[ToolCatalogItem]:
    from app.infra.db.repositories.tools import repository

    if not has_tool_workspace_access(actor, workspace_role):
        return []
    rows = await repository.list_tool_catalog_rows(
        db,
        workspace_id,
        actor.id,
        False,
        limit,
        offset,
        excluded_builtin_function_names=INTERNAL_BUILTIN_FUNCTION_NAMES,
    )
    items: list[ToolCatalogItem] = []
    for tool, source, version, policy, grant in rows:
        authorization = evaluate_tool_authorization(
            tool,
            actor,
            workspace_role,
            grant,
        )
        items.append(
            ToolCatalogItem(
                tool=tool,
                source=source,
                version=version,
                policy=policy,
                access=authorization.access,
                permission=authorization.permission,
            )
        )
    return items


async def get_tool_catalog_detail(
    db: AsyncSession,
    workspace_id: str,
    tool_id: str,
    actor: User,
    workspace_role: str | None,
) -> ToolCatalogDetail:
    from app.infra.db.repositories.tools import repository

    row = await repository.get_tool_catalog_detail_row(
        db,
        workspace_id,
        tool_id,
        actor.id,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found.")
    tool, source, version, policy, grant = row
    authorization = require_tool_view(
        evaluate_tool_authorization(tool, actor, workspace_role, grant)
    )
    return ToolCatalogDetail(
        tool=tool,
        source=source,
        version=version,
        policy=policy,
        authorization=authorization,
    )


def build_skill_script_tool(
    workspace_id: str, created_at: datetime | None = None
) -> tuple[Tool, ToolVersion, ToolPolicy]:
    timestamp = created_at or utc_now()
    source_id = stable_catalog_id(f"source:{workspace_id}:builtin")
    tool_id = stable_catalog_id(f"tool:{workspace_id}:builtin:run_skill_script")
    input_schema = {
        "type": "object",
        "properties": {
            "version_id": {"type": "string", "minLength": 1, "maxLength": 36},
            "path": {"type": "string", "minLength": 1, "maxLength": 255},
            "inputs": {"type": "object"},
            "filename": {"type": "string", "maxLength": 255},
        },
        "required": ["version_id", "path", "inputs"],
        "additionalProperties": False,
    }
    description = (
        "Execute a .py or .js script from an authorized, pinned Skill package in an isolated OpenSandbox. "
        "Load the Skill first. Scripts receive JSON inputs on stdin, package files under NEXAFLOW_SKILL_DIR, "
        "and may write a file to NEXAFLOW_OUTPUT_PATH when filename is supplied. Network is denied."
    )
    execution_spec = {"builtin": "skill_script"}
    definition_hash = canonical_definition_hash(
        {
            "name": "run_skill_script",
            "description": description,
            "input_schema": input_schema,
            "output_schema": None,
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
            stable_key="run_skill_script",
            function_name="run_skill_script",
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
            display_name="Skill script",
            description=description,
            input_schema=input_schema,
            output_schema=None,
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


def build_shell_tool(workspace_id: str, created_at: datetime | None = None) -> tuple[Tool, ToolVersion, ToolPolicy]:
    tool, version, policy = build_skill_script_tool(workspace_id, created_at)
    tool_id = stable_catalog_id(f"tool:{workspace_id}:builtin:bash")
    description = (
        "Run a bash command in this Run's persistent private workspace. Network is denied. "
        "Read authorized Skills under /skills/ and write deliverables to /workspace/outputs/. "
        "Files written there, including self-contained HTML pages, are automatically exported "
        "in artifacts[] with a filename and download_url. Use that URL to deliver the file. "
        "Files and installed Skill packages persist between calls; background processes are stopped after each command. "
        "Exit status and timeouts are returned as results. Output is limited to 30 KiB. "
        + _SPREADSHEET_VALUE_GUIDANCE
    )
    schema = {"type": "object", "properties": {
        "command": {"type": "string", "minLength": 1, "maxLength": 32768},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300, "default": 60},
    }, "required": ["command"], "additionalProperties": False}
    spec = {"builtin": "shell"}
    digest = canonical_definition_hash({"name": "bash", "description": description, "input_schema": schema, "output_schema": None, "execution_spec": spec})
    version_id = stable_catalog_id(f"version:{tool_id}:{digest}")
    return (
        replace(tool, id=tool_id, stable_key="bash", function_name="bash", current_version_id=version_id),
        replace(version, id=version_id, tool_id=tool_id, display_name="Command line", description=description, input_schema=schema, execution_spec=spec, definition_hash=digest),
        replace(policy, id=stable_catalog_id(f"policy:{tool_id}"), tool_id=tool_id, tool_version_id=version_id, definition_hash=digest),
    )


def build_skill_dependency_installer_tool(
    workspace_id: str, created_at: datetime | None = None
) -> tuple[Tool, ToolVersion, ToolPolicy]:
    timestamp = created_at or utc_now()
    source_id = stable_catalog_id(f"source:{workspace_id}:builtin")
    tool_id = stable_catalog_id(
        f"tool:{workspace_id}:builtin:install_skill_dependencies"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "version_id": {"type": "string", "minLength": 1, "maxLength": 36},
            "manager": {"type": "string", "enum": ["python", "node"]},
            "packages": {
                "type": "array",
                "items": {"type": "string", "minLength": 3, "maxLength": 255},
                "minItems": 1,
                "maxItems": 16,
                "uniqueItems": True,
            },
        },
        "required": ["version_id", "manager", "packages"],
        "additionalProperties": False,
    }
    description = (
        "Install exact-version Python or Node dependencies for one authorized, "
        "pinned Skill in this Agent Run's isolated OpenSandbox. This call always "
        "requires user approval. Use Python package==version or Node package@version; "
        "URLs, paths, ranges, tags, lifecycle scripts, source builds, and host installs "
        "are denied. After approval, retry run_skill_script."
    )
    execution_spec = {"builtin": "skill_dependency_install"}
    definition_hash = canonical_definition_hash(
        {
            "name": "install_skill_dependencies",
            "description": description,
            "input_schema": input_schema,
            "output_schema": None,
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
            stable_key="install_skill_dependencies",
            function_name="install_skill_dependencies",
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
            display_name="Install Skill dependencies",
            description=description,
            input_schema=input_schema,
            output_schema=None,
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
            approval="each_call",
            effect="external_write",
            allowed_access_sources=["console", "public"],
            workflow_callable=True,
            parallel_safe=False,
            created_at=timestamp,
            updated_at=timestamp,
        ),
    )


def build_artifact_tool(
    workspace_id: str,
    created_at: datetime | None = None,
) -> tuple[Tool, ToolVersion, ToolPolicy]:
    timestamp = created_at or utc_now()
    source_id = stable_catalog_id(f"source:{workspace_id}:builtin")
    tool_id = stable_catalog_id(f"tool:{workspace_id}:builtin:python_artifact")
    description = (
        "Create or rewrite a downloadable file of any common type. Choose the exact "
        "filename; its extension determines the file type, and extensionless names "
        "are supported. For plain-text and source-code files, put the exact final "
        "file contents in content; they are saved without being executed. For DOCX, "
        "PDF, XLSX, PPTX, images, and other rich or binary formats, put a Python "
        "generator program in content and write the final file only to the provided "
        "global output_path; never use /tmp, the current directory, or a hard-coded "
        "path. Use these installed libraries and import names: DOCX uses "
        "python-docx (`from docx import Document`); PDF uses PyMuPDF "
        "(`import pymupdf`); XLSX uses openpyxl; PPTX uses "
        "python-pptx (`from pptx import Presentation`); images use Pillow "
        "(`from PIL import Image`). Managed Skills may be selected with `skills`: "
        "built-in bundles are `documents`, `pdf`, `pptx`, and `spreadsheets`; their files "
        "are read-only below `NEXAFLOW_SKILLS_DIR`. Dependencies are pinned in the "
        "platform execution image, not installed from Skill requirements at runtime. "
        "Execution is network-denied. Do not install packages yourself, use package "
        "URLs, or create diagnostic files. The Python standard library is also available. User "
        "attachment text is already included in the conversation and can be used "
        "to produce an edited copy. Enforce requested measurable constraints in "
        "the generator before saving, and print concise validation results to stdout. "
        "The returned metadata includes stdout. Include the returned download_url "
        "verbatim in the final answer."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "maxLength": 262144,
                "description": (
                    "Exact UTF-8 contents for plain-text/source files, or Python "
                    "generator code for rich/binary output that writes to output_path. "
                    "For PDF import pymupdf, or select the `pdf` Skill for its "
                    "additional PDF packages."
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
            "skills": {
                "type": "array",
                "items": {
                    "type": "string",
                    "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$",
                },
                "maxItems": 8,
                "uniqueItems": True,
                "description": (
                    "Optional managed Skills to stage for the Python generator. "
                    "Built-ins: documents, pdf, pptx, spreadsheets."
                ),
            },
        },
        "required": ["content", "filename"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "maxLength": 36},
            "relative_path": {"type": ["string", "null"], "maxLength": 512},
            "content_hash": {"type": ["string", "null"], "maxLength": 64},
            "previous_artifact_id": {"type": ["string", "null"], "maxLength": 36},
            "inspection": {"type": "object"},
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
                        "relative_path": {"type": ["string", "null"], "maxLength": 512},
                        "content_hash": {"type": ["string", "null"], "maxLength": 64},
                        "previous_artifact_id": {
                            "type": ["string", "null"],
                            "maxLength": 36,
                        },
                        "inspection": {"type": "object"},
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
    definition_hash = canonical_definition_hash(
        {
            "name": "create_artifact",
            "description": description,
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
            # Keep the deterministic ID path for existing ToolRefs; the public
            # identity is now the generic built-in artifact capability.
            stable_key="artifact",
            function_name="create_artifact",
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
            display_name="Create downloadable file",
            description=description,
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


def build_image_generation_tool(
    workspace_id: str,
    created_at: datetime | None = None,
) -> tuple[Tool, ToolVersion, ToolPolicy]:
    timestamp = created_at or utc_now()
    tool_id = stable_catalog_id(f"tool:{workspace_id}:builtin:generate_image")
    description = (
        "Generate one PNG image from a text prompt using the image model selected for "
        "this Agent, or the workspace's single active OpenAI-compatible IMAGE model when "
        "the Agent selects none. Use this for requested artwork or illustrations, not "
        "for drawing charts or editing uploaded images. A user must approve each paid "
        "generation. The resulting image can be previewed and downloaded for 24 hours; "
        "include its filename and download link in the response."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "minLength": 1, "maxLength": 4000},
            "filename": {
                "type": "string",
                "minLength": 1,
                "maxLength": 60,
                "description": (
                    "Short file name for this image, without extension: name it after the "
                    "user's own wording in their language, at most 20 characters, and never "
                    "copy the expanded prompt. Defaults to the request wording."
                ),
            },
            "size": {
                "type": "string",
                "enum": ["square", "landscape", "portrait"],
                "description": "Image orientation; defaults to square.",
            },
            "resolution": {
                "type": "string",
                "enum": ["1K", "2K", "4K"],
                "description": (
                    "Output resolution tier. Use 2K or 4K only when the configured "
                    "image provider supports it; defaults to 1K."
                ),
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "maxLength": 36},
            "format": {"const": "png"},
            "filename": {"type": "string", "maxLength": 120},
            "mime_type": {"const": "image/png"},
            "download_url": {"type": "string", "maxLength": 4096},
            "preview_url": {"type": "string", "maxLength": 4096},
            "expires_at": {"type": "string", "maxLength": 64},
            "size_bytes": {"type": "integer", "minimum": 1, "maximum": 5242880},
        },
        "required": [
            "artifact_id", "format", "filename", "mime_type", "download_url",
            "preview_url", "expires_at", "size_bytes",
        ],
        "additionalProperties": False,
    }
    execution_spec = {"builtin": "image_generation"}
    definition_hash = canonical_definition_hash({
        "name": "generate_image",
        "description": description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "execution_spec": execution_spec,
    })
    version_id = stable_catalog_id(f"version:{tool_id}:{definition_hash}")
    return (
        Tool(
            id=tool_id,
            workspace_id=workspace_id,
            source_id=stable_catalog_id(f"source:{workspace_id}:builtin"),
            kind="builtin",
            stable_key="image_generation",
            function_name="generate_image",
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
            display_name="Generate image",
            description=description,
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
            approval="each_call",
            effect="external_write",
            allowed_access_sources=["console", "public"],
            workflow_callable=False,
            parallel_safe=False,
            created_at=timestamp,
            updated_at=timestamp,
        ),
    )


def build_skill_artifact_tool(
    workspace_id: str,
    skill_name: str,
    created_at: datetime | None = None,
) -> tuple[Tool, ToolVersion, ToolPolicy]:
    definition = next(
        (
            item
            for item in BUILTIN_SKILL_DEFINITIONS
            if item[0] == skill_name
        ),
        None,
    )
    if definition is None:
        raise ValueError(f"Unknown built-in Skill: {skill_name}")

    _, function_name, display_name, description = definition
    tool, version, policy = build_artifact_tool(workspace_id, created_at)
    tool_id = stable_catalog_id(
        f"tool:{workspace_id}:builtin:skill:{skill_name}"
    )
    input_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    execution_spec = {
        "builtin": "skill_guide",
        "skill": skill_name,
        "instructions": skill_instructions(skill_name),
    }
    version.output_schema = {
        "type": "object",
        "properties": {
            "skill": {"const": skill_name},
            "instructions": {"type": "string"},
        },
        "required": ["skill", "instructions"],
        "additionalProperties": False,
    }
    policy.workflow_callable = True
    definition_hash = canonical_definition_hash(
        {
            "name": function_name,
            "description": description,
            "input_schema": input_schema,
            "output_schema": version.output_schema,
            "execution_spec": execution_spec,
        }
    )
    version_id = stable_catalog_id(f"version:{tool_id}:{definition_hash}")

    tool.id = tool_id
    tool.stable_key = f"skill_{skill_name}"
    tool.function_name = function_name
    tool.current_version_id = version_id
    version.id = version_id
    version.tool_id = tool_id
    version.display_name = display_name
    version.description = description
    version.input_schema = input_schema
    version.execution_spec = execution_spec
    version.definition_hash = definition_hash
    policy.id = stable_catalog_id(f"policy:{tool_id}")
    policy.tool_id = tool_id
    policy.tool_version_id = version_id
    policy.definition_hash = definition_hash
    return tool, version, policy


async def ensure_workspace_system_catalog(
    db: AsyncSession,
    workspace_id: str,
) -> None:
    from app.infra.db.repositories.tools import repository

    source = ToolSource(
        id=stable_catalog_id(f"source:{workspace_id}:builtin"),
        workspace_id=workspace_id,
        kind="builtin",
        name="Built-in",
    )
    if await repository.get_tool_source(db, workspace_id, source.id) is None:
        await repository.save_tool_source(db, source)

    async def ensure_tool(
        desired_tool: Tool,
        desired_version: ToolVersion,
        desired_policy: ToolPolicy,
    ) -> None:
        tool = await repository.get_tool(db, workspace_id, desired_tool.id)
        if tool is None:
            desired_tool.current_version_id = None
            tool = await repository.save_tool(db, desired_tool)
        if (
            await repository.get_tool_version(db, workspace_id, desired_version.id)
            is None
        ):
            await repository.save_tool_version(db, desired_version)
        if await repository.get_tool_policy(db, workspace_id, desired_tool.id) is None:
            await repository.save_tool_policy(db, desired_policy)
        if tool.current_version_id is None:
            tool.current_version_id = desired_version.id
            await repository.save_tool(db, tool)

    await ensure_tool(*build_skill_script_tool(workspace_id))
    await ensure_tool(*build_shell_tool(workspace_id))
    await ensure_tool(*build_skill_dependency_installer_tool(workspace_id))
    await ensure_tool(*build_image_generation_tool(workspace_id))
    for skill_name, *_ in BUILTIN_SKILL_DEFINITIONS:
        await ensure_tool(*build_skill_artifact_tool(workspace_id, skill_name))


async def _tombstone_mcp_sources(
    db: AsyncSession,
    sources: list[ToolSource],
) -> None:
    from app.infra.db.repositories.tools import repository

    timestamp = utc_now()
    for source in sources:
        tools = await repository.list_tools_by_source(
            db,
            source.workspace_id,
            source.id,
        )
        for tool in tools:
            tool.status = "archived"
            tool.availability = "unavailable"
            tool.updated_at = timestamp
            await repository.save_tool(db, tool)
        source.status = "archived"
        source.mcp_server_id = None
        source.name = f"archived-mcp-{source.id}-{uuid4()}"
        source.updated_at = timestamp
        await repository.save_tool_source(db, source)


async def tombstone_mcp_server_catalog(
    db: AsyncSession,
    workspace_id: str,
    mcp_server_id: str,
) -> None:
    from app.infra.db.repositories.tools import repository

    sources = await repository.list_mcp_tool_sources(
        db,
        workspace_id,
        mcp_server_id,
    )
    await _tombstone_mcp_sources(db, sources)


async def tombstone_workspace_mcp_catalog(
    db: AsyncSession,
    workspace_id: str,
) -> None:
    from app.infra.db.repositories.tools import repository

    sources = await repository.list_mcp_tool_sources(db, workspace_id)
    await _tombstone_mcp_sources(db, sources)
