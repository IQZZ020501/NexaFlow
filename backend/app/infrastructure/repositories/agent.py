from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shareddomain.agents.models import (
    Agent,
    AgentKnowledgeBase,
    AgentMcpTool,
    AgentRun,
)


async def list_agents(
    db: AsyncSession,
    workspace_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[Agent]:
    result = await db.scalars(
        select(Agent)
        .where(Agent.workspace_id == workspace_id)
        .order_by(Agent.created_at.desc(), Agent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())


async def get_agent_by_id(db: AsyncSession, agent_id: str) -> Agent | None:
    return await db.get(Agent, agent_id)


async def list_binding_map(
    db: AsyncSession,
    agent_ids: list[str],
) -> dict[str, list[str]]:
    bindings = {agent_id: [] for agent_id in agent_ids}
    if not agent_ids:
        return bindings
    rows = await db.execute(
        select(AgentKnowledgeBase.agent_id, AgentKnowledgeBase.knowledge_base_id)
        .where(AgentKnowledgeBase.agent_id.in_(agent_ids))
        .order_by(AgentKnowledgeBase.created_at)
    )
    for agent_id, knowledge_base_id in rows.all():
        bindings[agent_id].append(knowledge_base_id)
    return bindings


async def replace_bindings(
    db: AsyncSession,
    agent: Agent,
    knowledge_base_ids: list[str],
) -> None:
    await db.execute(
        delete(AgentKnowledgeBase).where(AgentKnowledgeBase.agent_id == agent.id)
    )
    db.add_all(
        [
            AgentKnowledgeBase(
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                knowledge_base_id=knowledge_base_id,
            )
            for knowledge_base_id in knowledge_base_ids
        ]
    )


async def list_mcp_binding_map(
    db: AsyncSession,
    agent_ids: list[str],
) -> dict[str, list[dict[str, str]]]:
    bindings: dict[str, list[dict[str, str]]] = {
        agent_id: [] for agent_id in agent_ids
    }
    if not agent_ids:
        return bindings
    rows = await db.execute(
        select(
            AgentMcpTool.agent_id,
            AgentMcpTool.mcp_server_id,
            AgentMcpTool.tool_name,
        )
        .where(AgentMcpTool.agent_id.in_(agent_ids))
        .order_by(AgentMcpTool.created_at)
    )
    for agent_id, server_id, tool_name in rows.all():
        bindings[agent_id].append(
            {"server_id": server_id, "tool_name": tool_name}
        )
    return bindings


async def replace_mcp_bindings(
    db: AsyncSession,
    agent: Agent,
    references: list[dict[str, str]],
) -> None:
    await db.execute(
        delete(AgentMcpTool).where(AgentMcpTool.agent_id == agent.id)
    )
    db.add_all(
        [
            AgentMcpTool(
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                mcp_server_id=reference["server_id"],
                tool_name=reference["tool_name"],
            )
            for reference in references
        ]
    )


async def list_agent_runs(
    db: AsyncSession,
    agent_id: str,
    requested_by_user_id: str,
    limit: int | None = None,
    offset: int = 0,
    *,
    status: str | None = None,
) -> list[AgentRun]:
    statement = (
        select(AgentRun)
        .where(
            AgentRun.agent_id == agent_id,
            AgentRun.requested_by_user_id == requested_by_user_id,
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if status is not None:
        statement = statement.where(AgentRun.status == status)
    result = await db.scalars(statement)
    return list(result.all())


async def delete_agent_graph(db: AsyncSession, agent_id: str) -> None:
    await db.execute(delete(AgentRun).where(AgentRun.agent_id == agent_id))
    await db.execute(delete(AgentMcpTool).where(AgentMcpTool.agent_id == agent_id))
    await db.execute(
        delete(AgentKnowledgeBase).where(AgentKnowledgeBase.agent_id == agent_id)
    )
    await db.execute(delete(Agent).where(Agent.id == agent_id))
