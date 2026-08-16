import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from mcp.types import Tool as McpTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.tools import Tool, ToolPolicy, ToolSource, ToolVersion
from app.infrastructure.model_utils import utc_now


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
    return canonical_definition_hash(
        {
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
    )


def mcp_function_name(server_id: str, tool_name: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_name).strip("_")[:40] or "tool"
    digest = hashlib.sha256(f"{server_id}:{tool_name}".encode()).hexdigest()[:8]
    return f"mcp_{stem}_{digest}"


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


async def ensure_workspace_system_catalog(
    db: AsyncSession,
    workspace_id: str,
) -> None:
    from app.infrastructure.repositories import tools as repository

    catalog = build_workspace_system_catalog(workspace_id)
    for source in catalog.sources:
        if await repository.get_tool_source(db, workspace_id, source.id) is None:
            await repository.save_tool_source(db, source)

    tool = await repository.get_tool(db, workspace_id, catalog.tool.id)
    if tool is None:
        catalog.tool.current_version_id = None
        tool = await repository.save_tool(db, catalog.tool)

    if (
        await repository.get_tool_version(db, workspace_id, catalog.version.id)
        is None
    ):
        await repository.save_tool_version(db, catalog.version)

    if await repository.get_tool_policy(db, workspace_id, catalog.tool.id) is None:
        await repository.save_tool_policy(db, catalog.policy)

    if tool.current_version_id is None:
        tool.current_version_id = catalog.version.id
        await repository.save_tool(db, tool)
