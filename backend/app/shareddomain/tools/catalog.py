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
            "description": "Run inline Python in the Workflow sandbox.",
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
            description="Run inline Python in the Workflow sandbox.",
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


def build_python_artifact_tool(
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
                "maxLength": 262144,
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
        },
        "required": [
            "artifact_id",
            "format",
            "filename",
            "download_url",
            "expires_at",
            "size_bytes",
            "stdout",
        ],
        "additionalProperties": False,
    }
    execution_spec = {"builtin": "python_artifact"}
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
            stable_key="python_artifact",
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
    await ensure_tool(*build_python_artifact_tool(workspace_id))


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
