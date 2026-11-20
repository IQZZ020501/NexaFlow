from sqlalchemy import or_, select, union_all

from app.domain.tools.catalog.visibility import (
    INTERNAL_BUILTIN_FUNCTION_NAMES,
    MODEL_CONFIGURED_FUNCTION_NAMES,
)
from app.domain.tools.models import Tool, ToolSource


def tool_catalog_conditions(
    workspace_id: str, *, include_model_tools: bool = False, tool=Tool
):
    """Shared workspace inventory scope before applying a caller's access grants."""
    excluded = INTERNAL_BUILTIN_FUNCTION_NAMES + (
        () if include_model_tools else MODEL_CONFIGURED_FUNCTION_NAMES
    )
    return (
        tool.workspace_id == workspace_id,
        tool.status != "archived",
        tool.kind.in_(("builtin", "mcp", "integration")),
        or_(
            tool.kind != "builtin",
            tool.function_name.not_in(excluded),
        ),
    )


def tool_inventory_resources(workspace_id: str):
    """One row per catalog builtin or MCP source, including sources without tools."""
    return union_all(
        select(Tool.kind, Tool.status).where(
            *tool_catalog_conditions(workspace_id),
            Tool.kind == "builtin",
        ),
        select(ToolSource.kind, ToolSource.status).where(
            ToolSource.workspace_id == workspace_id,
            ToolSource.kind == "mcp",
            ToolSource.status != "archived",
        ),
    ).subquery()
