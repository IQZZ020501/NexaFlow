from sqlalchemy import or_

from app.domain.tools.catalog.visibility import (
    INTERNAL_BUILTIN_FUNCTION_NAMES,
    MODEL_CONFIGURED_FUNCTION_NAMES,
)
from app.domain.tools.models import Tool


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
        tool.kind.in_(("builtin", "mcp")),
        or_(
            tool.kind != "builtin",
            tool.function_name.not_in(excluded),
        ),
    )
