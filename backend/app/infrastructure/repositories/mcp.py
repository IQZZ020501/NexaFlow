from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.tools import McpServer
from app.infrastructure.repositories.mapping import (
    refresh_entity,
    save,
    to_entity,
)
from app.shareddomain.agents.models import AgentMcpTool
from app.shareddomain.tools.models import McpServer as McpServerOrm


async def list_mcp_servers(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[McpServer]:
    result = await db.scalars(
        select(McpServerOrm)
        .where(McpServerOrm.workspace_id == workspace_id)
        .order_by(McpServerOrm.created_at.desc(), McpServerOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(McpServer, row) for row in result.all()]


async def list_mcp_servers_by_ids(
    db: AsyncSession,
    workspace_id: str,
    server_ids: list[str],
) -> list[McpServer]:
    if not server_ids:
        return []
    result = await db.scalars(
        select(McpServerOrm).where(
            McpServerOrm.workspace_id == workspace_id,
            McpServerOrm.id.in_(server_ids),
        )
    )
    return [to_entity(McpServer, row) for row in result.all()]


async def get_mcp_server_by_id(db: AsyncSession, server_id: str) -> McpServer | None:
    row = await db.get(McpServerOrm, server_id)
    return to_entity(McpServer, row) if row is not None else None


async def create_mcp_server(
    db: AsyncSession,
    entity: McpServer,
) -> McpServer:
    row = await save(db, McpServerOrm, entity)
    return to_entity(McpServer, row)


async def save_mcp_server(db: AsyncSession, entity: McpServer) -> None:
    await save(db, McpServerOrm, entity)


async def refresh_mcp_server(
    db: AsyncSession,
    entity: McpServer,
) -> McpServer:
    return await refresh_entity(db, McpServerOrm, McpServer, entity)


async def delete_mcp_server(db: AsyncSession, entity: McpServer) -> None:
    await db.execute(
        delete(AgentMcpTool).where(AgentMcpTool.mcp_server_id == entity.id)
    )
    row = await db.get(McpServerOrm, entity.id)
    if row is not None:
        await db.delete(row)
