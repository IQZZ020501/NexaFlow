import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.agents import Agent
from app.entities.user import User
from app.entities.workflows import WorkflowDefinition, WorkflowVersion
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import knowledge as knowledge_base_repository
from app.infrastructure.repositories import workflow as workflow_repository
from app.ports.model_registry import get_registered_model_by_id
from app.schemas.workflow import (
    KnowledgeNodeConfig,
    LlmNodeConfig,
    McpNodeConfig,
    RerankerNodeConfig,
    WorkflowDefinitionResponse,
    WorkflowGraph,
    WorkflowVersionResponse,
)
from app.shareddomain.agents.permissions import require_agent_edit, require_agent_view
from app.shareddomain.agents.services import (
    agent_publication_snapshot,
    get_agent,
    get_agent_model,
)
from app.shareddomain.knowledge.services import (
    ACTIVE_STATUS as KNOWLEDGE_ACTIVE_STATUS,
    RESOURCE_TYPE as KNOWLEDGE_RESOURCE_TYPE,
    effective_permission,
)
from app.shareddomain.tools.services import (
    effective_mcp_tool_policy_mode,
    get_mcp_tool_policy,
    resolve_mcp_tools,
)
from app.shareddomain.workflows.defaults import default_workflow_graph
from app.shareddomain.workflows.engine import (
    WorkflowValidationError,
    graph_hash,
    validate_graph,
)

OUTPUT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def definition_to_response(definition: WorkflowDefinition) -> WorkflowDefinitionResponse:
    return WorkflowDefinitionResponse(
        id=definition.id,
        workspace_id=definition.workspace_id,
        agent_id=definition.agent_id,
        revision=definition.revision,
        graph=WorkflowGraph.model_validate(definition.graph),
        graph_hash=definition.graph_hash,
        updated_by_user_id=definition.updated_by_user_id,
        created_at=definition.created_at,
        updated_at=definition.updated_at,
    )


def version_to_response(version: WorkflowVersion) -> WorkflowVersionResponse:
    return WorkflowVersionResponse(
        id=version.id,
        workspace_id=version.workspace_id,
        agent_id=version.agent_id,
        definition_id=version.definition_id,
        definition_revision=version.definition_revision,
        version_number=version.version_number,
        default_model_id=version.default_model_id,
        graph=WorkflowGraph.model_validate(version.graph),
        graph_hash=version.graph_hash,
        published_by_user_id=version.published_by_user_id,
        created_at=version.created_at,
    )


async def get_workflow_agent(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
) -> Agent:
    agent = await get_agent(db, workspace_id, agent_id)
    if agent.app_type != "workflow":
        raise HTTPException(status.HTTP_409_CONFLICT, "Application is not a workflow.")
    return agent


async def validate_workflow_resources(
    db: AsyncSession,
    agent: Agent,
    graph: WorkflowGraph | dict[str, Any],
    actor: User,
    workspace_role: str | None,
    default_model_id: str | None = None,
) -> WorkflowGraph:
    try:
        parsed = validate_graph(graph)
    except WorkflowValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    knowledge_base_ids, mcp_tools = workflow_resource_references(parsed)
    model_ids = {default_model_id or agent.model_id}
    reranker_model_ids: set[str] = set()
    for node in parsed.nodes:
        config = node.data.config
        if node.data.type == "end":
            if any(
                OUTPUT_NAME_PATTERN.fullmatch(str(key)) is None
                for key in config.get("outputs", {})
            ):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"End node {node.id} output names are invalid.",
                )
        elif node.data.type in {"llm", "classifier"} and config.get("model_id"):
            model_ids.add(str(config["model_id"]))
        elif node.data.type == "reranker-node":
            reranker_model_ids.add(
                RerankerNodeConfig.model_validate(config).reranker_model_id
            )

    for model_id in model_ids:
        await get_agent_model(db, agent.workspace_id, model_id)
    for model_id in reranker_model_ids:
        model = await get_registered_model_by_id(db, model_id)
        if (
            model is None
            or model.workspace_id != agent.workspace_id
            or model.model_type != "RERANKER"
            or model.status != "active"
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Workflow reranker model is unavailable.",
            )
    knowledge_rows = await knowledge_base_repository.list_knowledge_bases_with_user_grants(
        db,
        agent.workspace_id,
        knowledge_base_ids,
        actor.id,
        KNOWLEDGE_RESOURCE_TYPE,
    )
    knowledge_by_id = {
        knowledge_base.id: (knowledge_base, grant)
        for knowledge_base, grant in knowledge_rows
    }
    for knowledge_base_id in knowledge_base_ids:
        row = knowledge_by_id.get(knowledge_base_id)
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Knowledge base not found.",
            )
        knowledge_base, grant = row
        if effective_permission(
            knowledge_base,
            actor,
            workspace_role,
            grant,
        ) not in {"view", "edit"}:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Knowledge base access denied.",
            )
        if knowledge_base.status != KNOWLEDGE_ACTIVE_STATUS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Workflow knowledge bases must be active.",
            )
    if mcp_tools:
        resolved = await resolve_mcp_tools(
            db,
            agent.workspace_id,
            mcp_tools,
            strict=True,
        )
        for tool in resolved:
            policy = await get_mcp_tool_policy(
                db,
                agent.workspace_id,
                tool.server.id,
                tool.definition.name,
            )
            if (
                policy is None
                or effective_mcp_tool_policy_mode(tool.definition, policy)
                != "read_only"
            ):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Workflow MCP nodes require a current read-only policy.",
                )
    return parsed


def workflow_resource_references(
    graph: WorkflowGraph,
) -> tuple[list[str], list[dict[str, str]]]:
    knowledge_base_ids: list[str] = []
    mcp_references: list[tuple[str, str]] = []
    for node in graph.nodes:
        config = node.data.config
        if node.data.type == "knowledge":
            knowledge_base_ids.extend(
                KnowledgeNodeConfig.model_validate(config).resolved_knowledge_base_ids
            )
        elif node.data.type == "mcp":
            mcp = McpNodeConfig.model_validate(config)
            mcp_references.append((mcp.server_id, mcp.tool_name))
        elif node.data.type == "llm":
            llm = LlmNodeConfig.model_validate(config)
            if llm.mcp_enable:
                mcp_references.extend(
                    (item.server_id, item.tool_name) for item in llm.mcp_servers
                )
    return (
        list(dict.fromkeys(knowledge_base_ids)),
        [
            {"server_id": server_id, "tool_name": tool_name}
            for server_id, tool_name in dict.fromkeys(mcp_references)
        ],
    )


async def get_or_create_definition(
    db: AsyncSession,
    agent: Agent,
    actor: User,
    workspace_role: str | None,
) -> WorkflowDefinition:
    await require_agent_view(db, agent, actor, workspace_role)
    definition = await workflow_repository.get_definition(
        db, agent.workspace_id, agent.id
    )
    if definition is not None:
        return definition
    require_agent_edit(agent, actor, workspace_role)
    graph = default_workflow_graph()
    definition = WorkflowDefinition(
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        graph=graph.model_dump(by_alias=True, mode="json"),
        graph_hash=graph_hash(graph),
        updated_by_user_id=actor.id,
    )
    definition = await workflow_repository.create_definition(db, definition)
    await db.commit()
    return await workflow_repository.refresh_definition(db, definition)


async def save_definition(
    db: AsyncSession,
    definition: WorkflowDefinition,
    graph: WorkflowGraph,
    expected_revision: int,
    actor: User,
) -> WorkflowDefinition:
    serialized = graph.model_dump(by_alias=True, mode="json")
    updated = await workflow_repository.update_definition_graph(
        db,
        definition.id,
        expected_revision,
        serialized,
        graph_hash(graph),
        actor.id,
    )
    if updated is None:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Workflow draft changed; reload it before saving.",
        )
    await db.commit()
    return await workflow_repository.refresh_definition(db, updated)


async def publish_definition(
    db: AsyncSession,
    agent: Agent,
    actor: User,
    workspace_role: str | None,
) -> WorkflowVersion:
    definition = await workflow_repository.lock_definition(
        db, agent.workspace_id, agent.id
    )
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow definition not found.")
    graph = await validate_workflow_resources(
        db, agent, definition.graph, actor, workspace_role
    )
    serialized = graph.model_dump(by_alias=True, mode="json")
    version = WorkflowVersion(
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        definition_id=definition.id,
        definition_revision=definition.revision,
        version_number=await workflow_repository.next_version_number(db, agent.id),
        default_model_id=agent.model_id,
        graph=serialized,
        graph_hash=graph_hash(serialized),
        published_by_user_id=actor.id,
    )
    version = await workflow_repository.create_version(db, version)
    bindings = (await agent_repository.list_binding_map(db, [agent.id]))[agent.id]
    mcp_bindings = (await agent_repository.list_mcp_binding_map(db, [agent.id]))[
        agent.id
    ]
    agent.published = True
    agent.published_snapshot = agent_publication_snapshot(
        agent, bindings, mcp_bindings
    )
    agent.published_by_user_id = actor.id
    agent.published_at = utc_now()
    await agent_repository.save_agent(db, agent)
    await db.commit()
    return version
