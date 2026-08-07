from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.agents import Agent as AgentEntity
from app.entities.agents import AgentRun as AgentRunEntity
from app.infrastructure.repositories.mapping import refresh_entity, save, to_entity
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
) -> list[AgentEntity]:
    result = await db.scalars(
        select(Agent)
        .where(Agent.workspace_id == workspace_id)
        .order_by(Agent.created_at.desc(), Agent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [to_entity(AgentEntity, row) for row in result.all()]


async def get_agent_by_id(db: AsyncSession, agent_id: str) -> AgentEntity | None:
    row = await db.get(Agent, agent_id)
    return to_entity(AgentEntity, row) if row is not None else None


async def create_agent(db: AsyncSession, entity: AgentEntity) -> AgentEntity:
    orm = await save(db, Agent, entity)
    return to_entity(AgentEntity, orm)


async def save_agent(db: AsyncSession, entity: AgentEntity) -> AgentEntity:
    orm = await save(db, Agent, entity)
    return to_entity(AgentEntity, orm)


async def refresh_agent(db: AsyncSession, entity: AgentEntity) -> AgentEntity:
    return await refresh_entity(db, Agent, AgentEntity, entity)


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
    agent: AgentEntity,
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
    agent: AgentEntity,
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
) -> list[AgentRunEntity]:
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
    return [to_entity(AgentRunEntity, row) for row in result.all()]


async def get_agent_run_by_id(
    db: AsyncSession,
    run_id: str,
) -> AgentRunEntity | None:
    row = await db.get(AgentRun, run_id)
    return to_entity(AgentRunEntity, row) if row is not None else None


async def create_agent_run(db: AsyncSession, entity: AgentRunEntity) -> AgentRunEntity:
    orm = await save(db, AgentRun, entity)
    return to_entity(AgentRunEntity, orm)


async def save_agent_run(db: AsyncSession, entity: AgentRunEntity) -> AgentRunEntity:
    orm = await save(db, AgentRun, entity)
    return to_entity(AgentRunEntity, orm)


async def refresh_agent_run(db: AsyncSession, entity: AgentRunEntity) -> AgentRunEntity:
    return await refresh_entity(db, AgentRun, AgentRunEntity, entity)


async def delete_agent_graph(db: AsyncSession, agent_id: str) -> None:
    await db.execute(delete(AgentRun).where(AgentRun.agent_id == agent_id))
    await db.execute(delete(AgentMcpTool).where(AgentMcpTool.agent_id == agent_id))
    await db.execute(
        delete(AgentKnowledgeBase).where(AgentKnowledgeBase.agent_id == agent_id)
    )
    await db.execute(delete(Agent).where(Agent.id == agent_id))


async def delete_workspace_agent_graph(db: AsyncSession, workspace_id: str) -> None:
    await db.execute(delete(AgentRun).where(AgentRun.workspace_id == workspace_id))
    await db.execute(
        delete(AgentMcpTool).where(AgentMcpTool.workspace_id == workspace_id)
    )
    await db.execute(
        delete(AgentKnowledgeBase).where(
            AgentKnowledgeBase.workspace_id == workspace_id
        )
    )
    await db.execute(delete(Agent).where(Agent.workspace_id == workspace_id))
