from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.tools import McpServer, McpToolPolicy
from app.infrastructure.repositories.mapping import (
    apply_to_orm,
    refresh_entity,
    save,
    to_entity,
    to_orm,
)
from app.shareddomain.agents.models import AgentMcpTool
from app.shareddomain.tools.models import McpServer as McpServerOrm
from app.shareddomain.tools.models import McpToolPolicy as McpToolPolicyOrm
from app.shareddomain.tools.models import ToolSource as ToolSourceOrm


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


async def list_manageable_mcp_servers(
    db: AsyncSession,
    workspace_id: str,
    actor_id: str,
    is_workspace_admin: bool,
    limit: int | None = None,
    offset: int = 0,
) -> list[McpServer]:
    statement = (
        select(McpServerOrm)
        .join(
            ToolSourceOrm,
            (ToolSourceOrm.workspace_id == McpServerOrm.workspace_id)
            & (ToolSourceOrm.mcp_server_id == McpServerOrm.id),
        )
        .where(
            McpServerOrm.workspace_id == workspace_id,
            ToolSourceOrm.kind == "mcp",
        )
    )
    if not is_workspace_admin:
        statement = statement.where(ToolSourceOrm.created_by_user_id == actor_id)
    rows = await db.scalars(
        statement
        .order_by(McpServerOrm.created_at.desc(), McpServerOrm.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(McpServer, row) for row in rows.all()]


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


async def list_mcp_servers_by_creator(
    db: AsyncSession,
    user_id: str,
) -> list[McpServer]:
    rows = await db.scalars(
        select(McpServerOrm)
        .where(McpServerOrm.created_by_user_id == user_id)
        .order_by(McpServerOrm.workspace_id, McpServerOrm.created_at, McpServerOrm.id)
    )
    return [to_entity(McpServer, row) for row in rows.all()]


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
        await db.flush()


async def delete_workspace_mcp_servers(db: AsyncSession, workspace_id: str) -> None:
    await db.execute(
        delete(AgentMcpTool).where(AgentMcpTool.workspace_id == workspace_id)
    )
    await db.execute(
        delete(McpServerOrm).where(McpServerOrm.workspace_id == workspace_id)
    )


async def get_mcp_tool_policy(
    db: AsyncSession,
    workspace_id: str,
    server_id: str,
    tool_name: str,
) -> McpToolPolicy | None:
    row = await db.scalar(
        select(McpToolPolicyOrm).where(
            McpToolPolicyOrm.workspace_id == workspace_id,
            McpToolPolicyOrm.mcp_server_id == server_id,
            McpToolPolicyOrm.tool_name == tool_name,
        )
    )
    return to_entity(McpToolPolicy, row) if row is not None else None


async def list_mcp_tool_policies(
    db: AsyncSession,
    workspace_id: str,
) -> list[McpToolPolicy]:
    rows = await db.scalars(
        select(McpToolPolicyOrm).where(
            McpToolPolicyOrm.workspace_id == workspace_id
        )
    )
    return [to_entity(McpToolPolicy, row) for row in rows.all()]


async def save_mcp_tool_policy(
    db: AsyncSession,
    entity: McpToolPolicy,
) -> McpToolPolicy:
    existing = await db.scalar(
        select(McpToolPolicyOrm).where(
            McpToolPolicyOrm.workspace_id == entity.workspace_id,
            McpToolPolicyOrm.mcp_server_id == entity.mcp_server_id,
            McpToolPolicyOrm.tool_name == entity.tool_name,
        )
    )
    if existing is None:
        try:
            async with db.begin_nested():
                row = to_orm(McpToolPolicyOrm, entity)
                db.add(row)
                await db.flush()
        except IntegrityError:
            existing = await db.scalar(
                select(McpToolPolicyOrm).where(
                    McpToolPolicyOrm.workspace_id == entity.workspace_id,
                    McpToolPolicyOrm.mcp_server_id == entity.mcp_server_id,
                    McpToolPolicyOrm.tool_name == entity.tool_name,
                )
            )
            if existing is None:
                raise
        else:
            return to_entity(McpToolPolicy, row)

    entity.id = existing.id
    entity.created_at = existing.created_at
    apply_to_orm(existing, entity)
    await db.flush()
    return to_entity(McpToolPolicy, existing)
