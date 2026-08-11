import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.agents import Agent
from app.entities.user import User
from app.entities.workflows import WorkflowDefinition, WorkflowVersion
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import workflow as workflow_repository
from app.schemas.workflow import (
    WorkflowDefinitionResponse,
    WorkflowGraph,
    WorkflowVersionResponse,
)
from app.shareddomain.agents.permissions import require_agent_edit, require_agent_view
from app.shareddomain.agents.services import get_agent, get_agent_model
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
    default_model_id: str | None = None,
) -> WorkflowGraph:
    try:
        parsed = validate_graph(graph)
    except WorkflowValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    bindings = (await agent_repository.list_binding_map(db, [agent.id]))[agent.id]
    mcp_bindings = (await agent_repository.list_mcp_binding_map(db, [agent.id]))[
        agent.id
    ]
    bound_mcp = {(item["server_id"], item["tool_name"]) for item in mcp_bindings}
    referenced_mcp: set[tuple[str, str]] = set()
    model_ids = {default_model_id or agent.model_id}
    input_names: list[str] = []
    for node in parsed.nodes:
        config = node.data.config
        if node.data.type == "start":
            input_names = [str(item["name"]) for item in config.get("inputs", [])]
            if len(input_names) != len(set(input_names)):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"Start node {node.id} input names must be unique.",
                )
        elif node.data.type == "end":
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
        elif node.data.type == "knowledge":
            if config["knowledge_base_id"] not in bindings:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"Knowledge node {node.id} uses an unbound knowledge base.",
                )
        elif node.data.type == "mcp":
            reference = (config["server_id"], config["tool_name"])
            if reference not in bound_mcp:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"MCP node {node.id} uses an unbound tool.",
                )
            referenced_mcp.add(reference)

    for model_id in model_ids:
        await get_agent_model(db, agent.workspace_id, model_id)
    if referenced_mcp:
        references = [
            item
            for item in mcp_bindings
            if (item["server_id"], item["tool_name"]) in referenced_mcp
        ]
        resolved = await resolve_mcp_tools(
            db,
            agent.workspace_id,
            references,
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
) -> WorkflowVersion:
    definition = await workflow_repository.lock_definition(
        db, agent.workspace_id, agent.id
    )
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow definition not found.")
    graph = await validate_workflow_resources(db, agent, definition.graph)
    version = WorkflowVersion(
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        definition_id=definition.id,
        definition_revision=definition.revision,
        version_number=await workflow_repository.next_version_number(db, agent.id),
        default_model_id=agent.model_id,
        graph=graph.model_dump(by_alias=True, mode="json"),
        graph_hash=definition.graph_hash,
        published_by_user_id=actor.id,
    )
    version = await workflow_repository.create_version(db, version)
    agent.published = True
    agent.published_by_user_id = actor.id
    agent.published_at = utc_now()
    await agent_repository.save_agent(db, agent)
    await db.commit()
    return version
