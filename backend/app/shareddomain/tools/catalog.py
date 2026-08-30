import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from fastapi import HTTPException, status
from mcp.types import Tool as McpTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.tools import (
    Tool,
    ToolAccess,
    ToolDraft,
    ToolPolicy,
    ToolSource,
    ToolVersion,
)
from app.entities.user import User
from app.infrastructure.model_utils import utc_now
from app.shareddomain.tools.permissions import (
    ToolAuthorization,
    ToolPermissionLabel,
    evaluate_tool_authorization,
    has_tool_workspace_access,
    require_tool_view,
)


CATALOG_ID_NAMESPACE = UUID("2df58f89-2f5c-4e2b-9545-d50fb806a6db")


BUILTIN_SKILL_DEFINITIONS = (
    (
        "documents",
        "documents_skill",
        "Documents Skill",
        "Create a DOCX file from Markdown content using the Documents Skill renderer.",
    ),
    (
        "pdf",
        "pdf_skill",
        "PDF Skill",
        "Create a paginated PDF from Markdown content using the PDF Skill renderer.",
    ),
    (
        "pptx",
        "pptx_skill",
        "PPTX Skill",
        (
            "Create a new 16:9 PPTX from audience-facing structured slides. "
            "Plan around the audience and purpose, give each slide one takeaway, "
            "keep the cover minimal, keep copy concise, vary the supported layouts, "
            "and put external sources in speaker notes. Keep titles and body text "
            "at readable sizes; the renderer rejects overlong slide titles. It "
            "supports built-in templates, "
            "brand colors, native icons, and tables; it does not edit existing "
            "decks or fetch external media."
        ),
    ),
    (
        "spreadsheets",
        "spreadsheets_skill",
        "Spreadsheets Skill",
        "Create a formatted XLSX workbook from structured sheet data using the Spreadsheets Skill renderer.",
    ),
)

INTERNAL_BUILTIN_FUNCTION_NAMES = (
    "create_artifact",
    "inline_python",
)


def _pptx_input_schema() -> dict[str, Any]:
    bullet_list = {
        "type": "array",
        "minItems": 1,
        "maxItems": 6,
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240,
        },
        "description": "Short audience-facing support points for one slide claim.",
    }
    column = {
        "type": "object",
        "properties": {
            "heading": {
                "type": "string",
                "minLength": 1,
                "maxLength": 60,
            },
            "bullets": {
                **bullet_list,
                "maxItems": 5,
            },
        },
        "required": ["heading", "bullets"],
        "additionalProperties": False,
    }
    icon_item = {
        "type": "object",
        "properties": {
            "icon": {
                "type": "string",
                "enum": [
                    "bolt",
                    "cloud",
                    "cycle",
                    "direction",
                    "focus",
                    "gear",
                    "growth",
                    "heart",
                    "star",
                    "sun",
                ],
                "description": "Built-in native PowerPoint icon.",
            },
            "title": {
                "type": "string",
                "minLength": 1,
                "maxLength": 48,
            },
            "body": {
                "type": "string",
                "minLength": 1,
                "maxLength": 180,
            },
        },
        "required": ["icon", "title", "body"],
        "additionalProperties": False,
    }
    table = {
        "type": "object",
        "properties": {
            "headers": {
                "type": "array",
                "minItems": 2,
                "maxItems": 5,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 60,
                },
            },
            "rows": {
                "type": "array",
                "minItems": 1,
                "maxItems": 7,
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 5,
                    "items": {
                        "type": [
                            "string",
                            "number",
                            "integer",
                            "boolean",
                            "null",
                        ]
                    },
                },
            },
        },
        "required": ["headers", "rows"],
        "additionalProperties": False,
        "description": "A compact native table; every row must match the headers.",
    }
    slide = {
        "type": "object",
        "properties": {
            "layout": {
                "type": "string",
                "enum": [
                    "section",
                    "bullets",
                    "two_column",
                    "icons",
                    "table",
                ],
                "description": (
                    "Use section for transitions, bullets for one claim with "
                    "supporting points, two_column for a direct comparison, icons "
                    "for 2-4 parallel concepts, and table for compact structured data."
                ),
            },
            "title": {
                "type": "string",
                "minLength": 1,
                "maxLength": 48,
                "description": (
                    "One-line takeaway title written for the intended audience, "
                    "not a topic label or planning note; keep it to roughly 30 "
                    "display-width units so it stays on one line."
                ),
            },
            "subtitle": {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
                "description": "Optional section-slide context; omit for other layouts.",
            },
            "bullets": bullet_list,
            "left": column,
            "right": column,
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": icon_item,
            },
            "table": table,
            "notes": {
                "type": "string",
                "maxLength": 4_000,
                "description": (
                    "Speaker notes. Put externally sourced claims under a "
                    "[Sources] block with traceable references."
                ),
            },
        },
        "required": ["layout", "title"],
        "additionalProperties": False,
        "description": (
            "Provide only the content field used by the selected layout: subtitle, "
            "bullets, left/right, items, or table."
        ),
    }
    return {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "minLength": 1,
                "maxLength": 120,
                "description": "Minimal cover title for the intended audience.",
            },
            "subtitle": {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
            },
            "template": {
                "type": "string",
                "enum": ["minimal", "editorial", "bold"],
                "description": "Built-in composition template; defaults to minimal.",
            },
            "brand": {
                "type": "object",
                "properties": {
                    "primary_color": {
                        "type": "string",
                        "pattern": r"^#[0-9A-Fa-f]{6}$",
                    },
                    "background_color": {
                        "type": "string",
                        "pattern": r"^#[0-9A-Fa-f]{6}$",
                    },
                    "text_color": {
                        "type": "string",
                        "pattern": r"^#[0-9A-Fa-f]{6}$",
                    },
                    "font_family": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 64,
                        "description": "Referenced PowerPoint font; it is not embedded.",
                    },
                },
                "required": [
                    "primary_color",
                    "background_color",
                    "text_color",
                    "font_family",
                ],
                "additionalProperties": False,
                "description": (
                    "Optional brand override. Text/background must meet readable "
                    "contrast and primary/background must remain visually distinct."
                ),
            },
            "footer": {
                "type": "string",
                "minLength": 1,
                "maxLength": 100,
            },
            "slides": {
                "type": "array",
                "minItems": 1,
                "maxItems": 30,
                "items": slide,
                "description": (
                    "Narrative-ordered content slides. Each slide should advance one "
                    "claim; vary adjacent layouts when the content supports it."
                ),
            },
        },
        "required": ["title", "slides"],
        "additionalProperties": False,
    }


def _skill_input_schema(skill_name: str) -> dict[str, Any]:
    filename_patterns = {
        "documents": r"^[^/\\]+\.[dD][oO][cC][xX]$",
        "pdf": r"^[^/\\]+\.[pP][dD][fF]$",
        "pptx": r"^[^/\\]+\.[pP][pP][tT][xX]$",
        "spreadsheets": r"^[^/\\]+\.[xX][lL][sS][xX]$",
    }
    properties: dict[str, Any] = {
        "filename": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120,
            "pattern": filename_patterns[skill_name],
        }
    }
    required = ["filename"]
    if skill_name in {"documents", "pdf"}:
        properties["content"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 200_000,
            "description": (
                "Final document content in a concise Markdown subset: headings, "
                "paragraphs, bullet or numbered lists, and pipe tables."
            ),
        }
        required.append("content")
    elif skill_name == "spreadsheets":
        properties["workbook"] = {
            "type": "object",
            "properties": {
                "sheets": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 16,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 31,
                            },
                            "rows": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 2_000,
                                "items": {
                                    "type": "array",
                                    "maxItems": 64,
                                    "items": {
                                        "type": [
                                            "string",
                                            "number",
                                            "integer",
                                            "boolean",
                                            "null",
                                        ]
                                    },
                                },
                            },
                            "freeze_panes": {
                                "type": "string",
                                "maxLength": 10,
                            },
                            "auto_filter": {"type": "boolean"},
                        },
                        "required": ["name", "rows"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["sheets"],
            "additionalProperties": False,
        }
        required.append("workbook")
    elif skill_name == "pptx":
        properties["presentation"] = _pptx_input_schema()
        required.append("presentation")
    else:
        raise ValueError(f"Unknown built-in Skill: {skill_name}")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


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
    return {
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
    from app.infrastructure.repositories import tools as repository
    from app.infrastructure.repositories import workspace as workspace_repository

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
                    workflow_callable=False,
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
class WorkspaceSystemCatalog:
    sources: tuple[ToolSource, ToolSource]
    tool: Tool
    version: ToolVersion
    policy: ToolPolicy


@dataclass(frozen=True)
class ToolCatalogItem:
    tool: Tool
    source: ToolSource
    version: ToolVersion | None
    draft: ToolDraft | None
    access: ToolAccess
    permission: ToolPermissionLabel | None


@dataclass(frozen=True)
class ToolCatalogDetail:
    tool: Tool
    source: ToolSource
    version: ToolVersion | None
    draft: ToolDraft | None
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
    from app.infrastructure.repositories import tools as repository

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
    from app.infrastructure.repositories import tools as repository

    if not has_tool_workspace_access(actor, workspace_role):
        return []
    rows = await repository.list_tool_catalog_rows(
        db,
        workspace_id,
        actor.id,
        workspace_role == "admin" or actor.is_global_admin,
        limit,
        offset,
        excluded_builtin_function_names=INTERNAL_BUILTIN_FUNCTION_NAMES,
    )
    items: list[ToolCatalogItem] = []
    for tool, source, version, draft, grant in rows:
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
                draft=draft,
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
    from app.infrastructure.repositories import tools as repository

    row = await repository.get_tool_catalog_detail_row(
        db,
        workspace_id,
        tool_id,
        actor.id,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found.")
    tool, source, version, draft, policy, grant = row
    authorization = require_tool_view(
        evaluate_tool_authorization(tool, actor, workspace_role, grant)
    )
    return ToolCatalogDetail(
        tool=tool,
        source=source,
        version=version,
        draft=draft,
        policy=policy,
        authorization=authorization,
    )


def build_workspace_system_catalog(
    workspace_id: str,
    created_at: datetime | None = None,
) -> WorkspaceSystemCatalog:
    timestamp = created_at or utc_now()
    builtin_source_id = stable_catalog_id(f"source:{workspace_id}:builtin")
    python_source_id = stable_catalog_id(f"source:{workspace_id}:python")
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
    execution_spec = {"builtin": "current_time"}
    definition_hash = canonical_definition_hash(
        {
            "name": "current_time",
            "description": "Return the current UTC time.",
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
            source_id=builtin_source_id,
            kind="builtin",
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
            description="Return the current UTC time.",
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
            parallel_safe=True,
            created_at=timestamp,
            updated_at=timestamp,
        ),
    )


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
        "are staged read-only below `NEXAFLOW_SKILLS_DIR`, and an optional "
        "`requirements.txt` is installed into `NEXAFLOW_PACKAGES_DIR` through the "
        "Worker public HTTP(S) proxy. Do not install packages yourself, use package "
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
    input_schema = _skill_input_schema(skill_name)
    execution_spec = {"builtin": "skill", "skill": skill_name}
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
    from app.infrastructure.repositories import tools as repository

    catalog = build_workspace_system_catalog(workspace_id)
    for source in catalog.sources:
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

    await ensure_tool(catalog.tool, catalog.version, catalog.policy)
    await ensure_tool(*build_inline_python_tool(workspace_id))
    for skill_name, *_ in BUILTIN_SKILL_DEFINITIONS:
        await ensure_tool(*build_skill_artifact_tool(workspace_id, skill_name))


async def _tombstone_mcp_sources(
    db: AsyncSession,
    sources: list[ToolSource],
) -> None:
    from app.infrastructure.repositories import tools as repository

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
    from app.infrastructure.repositories import tools as repository

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
    from app.infrastructure.repositories import tools as repository

    sources = await repository.list_mcp_tool_sources(db, workspace_id)
    await _tombstone_mcp_sources(db, sources)
