from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shareddomain.agents.models import AgentMcpTool
from app.shareddomain.tools.models import McpServer


async def list_mcp_servers(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[McpServer]:
    result = await db.scalars(
        select(McpServer)
        .where(McpServer.workspace_id == workspace_id)
        .order_by(McpServer.created_at.desc(), McpServer.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())


async def list_mcp_servers_by_ids(
    db: AsyncSession,
    workspace_id: str,
    server_ids: list[str],
) -> list[McpServer]:
    if not server_ids:
        return []
    result = await db.scalars(
        select(McpServer).where(
            McpServer.workspace_id == workspace_id,
            McpServer.id.in_(server_ids),
        )
    )
    return list(result.all())


async def get_mcp_server_by_id(db: AsyncSession, server_id: str) -> McpServer | None:
    return await db.get(McpServer, server_id)


async def delete_mcp_server(db: AsyncSession, server_id: str) -> None:
    await db.execute(
        delete(AgentMcpTool).where(AgentMcpTool.mcp_server_id == server_id)
    )
    await db.execute(delete(McpServer).where(McpServer.id == server_id))
