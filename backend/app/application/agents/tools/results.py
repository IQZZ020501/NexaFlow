"""Read retained MCP results within the executing Run's identity boundary."""

import json

from app.domain.agents.runtime.tools import AgentToolResult
from app.domain.tools.results import tool_result_page
from app.entities.runs import AgentRun
from app.infra.db.repositories.tools.invocations import read_agent_tool_result
from app.infra.db.session import get_session_factory
from app.ports.mcp import MAX_MCP_STORED_RESULT_BYTES


async def read_run_tool_result(
    run: AgentRun, result_id: str, offset: int, limit: int
) -> AgentToolResult:
    if (
        not isinstance(result_id, str)
        or not 1 <= len(result_id) <= 255
        or type(offset) is not int
        or not 0 <= offset <= MAX_MCP_STORED_RESULT_BYTES
        or type(limit) is not int
        or not 1 <= limit <= 12000
    ):
        raise ValueError("Invalid Tool result read range.")
    async with get_session_factory()() as db:
        stored = await read_agent_tool_result(
            db,
            workspace_id=run.workspace_id,
            run_id=run.id,
            execution_user_id=run.execution_user_id,
            access_source=run.access_source,
            result_id=result_id,
            offset=offset,
            limit=limit,
        )
    if stored is None:
        return AgentToolResult(
            content="Tool result is unavailable in this Run.",
            summary="Tool result unavailable.",
            is_error=True,
        )
    content, total_characters = stored
    page = tool_result_page(result_id, content, offset, total_characters)
    return AgentToolResult(
        content=json.dumps(page, ensure_ascii=False),
        summary="Stored Tool result read.",
        output=page,
    )
