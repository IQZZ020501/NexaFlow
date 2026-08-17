import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.agents import Agent
from app.entities.tools import ToolRef, ToolSnapshot
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
from app.shareddomain.agents.publications import agent_publication_hash
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
from app.shareddomain.tools.bindings import (
    resolve_application_tool_snapshots,
    resolve_tool_refs_for_actor,
    sync_application_tool_bindings,
)
from app.shareddomain.tools.catalog import build_inline_python_tool
from app.shareddomain.tools.runtime import tool_snapshot_from_payload
from app.shareddomain.workflows.defaults import default_workflow_graph
from app.shareddomain.workflows.engine import (
    WorkflowValidationError,
    graph_hash,
    validate_graph,
)
from app.shareddomain.workflows.resources import (
    build_workflow_resource_snapshot,
    canonicalize_workflow_graph,
    legacy_mcp_references as canonical_legacy_mcp_references,
    select_tool_snapshots,
    workflow_resource_hash,
    workflow_agent_version_references,
    workflow_resource_references as canonical_workflow_resource_references,
)

OUTPUT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


async def _workflow_agent_snapshots(
    db: AsyncSession,
    workspace_id: str,
    graph: WorkflowGraph,
    actor: User,
    workspace_role: str | None,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for version_id in workflow_agent_version_references(graph):
        version = await agent_repository.get_agent_publication_version(
            db,
            workspace_id,
            version_id,
        )
        if version is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Agent publication version not found.",
            )
        target = await get_agent(db, workspace_id, version.agent_id)
        await require_agent_view(db, target, actor, workspace_role)
        if (
            target.app_type != "agent"
            or target.status != "active"
            or not target.published
            or target.current_published_version_id is None
            or version.schema_version != 1
            or agent_publication_hash(
                version.configuration_snapshot,
                version.resource_snapshot,
            )
            != version.configuration_hash
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Workflow Agent publication is unavailable.",
            )
        try:
            tools = [
                tool_snapshot_from_payload(item)
                for item in version.resource_snapshot.get("tools", [])
            ]
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Workflow Agent publication is invalid.",
            ) from exc
        if any(
            tool.approval != "auto"
            or tool.effect not in {"pure", "external_read"}
            for tool in tools
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Workflow Agent Tools must be automatic and read-only.",
            )
        snapshots.append(
            {
                "agent_id": target.id,
                "version_id": version.id,
                "version_number": version.version_number,
                "configuration_hash": version.configuration_hash,
                "configuration_snapshot": version.configuration_snapshot,
                "resource_snapshot": version.resource_snapshot,
                "bound_by_user_id": actor.id,
            }
        )
    return snapshots


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


async def prepare_workflow_resources(
    db: AsyncSession,
    agent: Agent,
    graph: WorkflowGraph | dict[str, Any],
    actor: User,
    workspace_role: str | None,
    *,
    require_complete_graph: bool = True,
    binding_application_id: str | None = None,
) -> tuple[WorkflowGraph, list[ToolSnapshot], dict[str, Any], str]:
    """Validate and freeze every Workflow Tool before it is persisted or run."""
    if require_complete_graph:
        parsed = await validate_workflow_resources(
            db,
            agent,
            graph,
            actor,
            workspace_role,
            binding_application_id=binding_application_id,
        )
    else:
        try:
            parsed = WorkflowGraph.model_validate(graph)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                str(exc),
            ) from exc
    legacy_refs = canonical_legacy_mcp_references(parsed)
    legacy_tools: dict[tuple[str, str], ToolRef] = {}
    if legacy_refs:
        resolved = await resolve_mcp_tools(
            db,
            agent.workspace_id,
            [
                {"server_id": server_id, "tool_name": tool_name}
                for server_id, tool_name in legacy_refs
            ],
            strict=True,
            actor=actor if binding_application_id is None else None,
            workspace_role=workspace_role,
            application_id=binding_application_id,
        )
        legacy_tools = {
            (item.server.id, item.definition.name): ToolRef(
                tool_id=item.tool_id,
                version_id=item.tool_version_id,
            )
            for item in resolved
        }

    inline_tool, inline_version, _inline_policy = build_inline_python_tool(
        agent.workspace_id
    )
    canonical = canonicalize_workflow_graph(
        parsed,
        legacy_tools,
        ToolRef(inline_tool.id, inline_version.id),
    )
    _knowledge_base_ids, references = canonical_workflow_resource_references(canonical)
    if binding_application_id is None:
        snapshots = await resolve_tool_refs_for_actor(
            db,
            agent.workspace_id,
            references,
            actor,
            workspace_role,
        )
    else:
        try:
            snapshots = select_tool_snapshots(
                references,
                await resolve_application_tool_snapshots(
                    db,
                    agent.workspace_id,
                    binding_application_id,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    for snapshot in snapshots:
        if snapshot.approval != "auto" or not snapshot.workflow_callable:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Workflow Tools must be automatic and workflow-callable.",
            )
    llm_tool_ids = {
        item.tool_id
        for node in canonical.nodes
        if node.data.type == "llm"
        for item in LlmNodeConfig.model_validate(node.data.config).tools
    }
    if any(
        snapshot.tool_id in llm_tool_ids
        and snapshot.execution_spec.get("direct_only") is True
        for snapshot in snapshots
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This Workflow Tool can only be used as a direct node.",
        )
    agent_snapshots = await _workflow_agent_snapshots(
        db,
        agent.workspace_id,
        canonical,
        actor,
        workspace_role,
    )
    resource_snapshot = build_workflow_resource_snapshot(
        _knowledge_base_ids,
        snapshots,
        agent_snapshots,
    )
    return (
        canonical,
        snapshots,
        resource_snapshot,
        workflow_resource_hash(resource_snapshot),
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
    binding_application_id: str | None = None,
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
            actor=actor if binding_application_id is None else None,
            workspace_role=workspace_role,
            application_id=binding_application_id,
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
    agent: Agent,
    definition: WorkflowDefinition,
    graph: WorkflowGraph,
    expected_revision: int,
    actor: User,
    workspace_role: str | None,
) -> WorkflowDefinition:
    canonical, snapshots, _resource_snapshot, _resource_hash = (
        await prepare_workflow_resources(
            db,
            agent,
            graph,
            actor,
            workspace_role,
            require_complete_graph=False,
        )
    )
    serialized = canonical.model_dump(by_alias=True, mode="json")
    updated = await workflow_repository.update_definition_graph(
        db,
        definition.id,
        expected_revision,
        serialized,
        graph_hash(serialized),
        actor.id,
    )
    if updated is None:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Workflow draft changed; reload it before saving.",
        )
    await sync_application_tool_bindings(
        db,
        agent.workspace_id,
        agent.id,
        snapshots,
        actor.id,
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
    graph, snapshots, resource_snapshot, resource_hash = (
        await prepare_workflow_resources(
            db,
            agent,
            definition.graph,
            actor,
            workspace_role,
            binding_application_id=agent.id,
        )
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
        resource_snapshot=resource_snapshot,
        resource_hash=resource_hash,
        published_by_user_id=actor.id,
    )
    version = await workflow_repository.create_version(db, version)
    await sync_application_tool_bindings(
        db,
        agent.workspace_id,
        agent.id,
        snapshots,
        actor.id,
    )
    bindings = (await agent_repository.list_binding_map(db, [agent.id]))[agent.id]
    mcp_bindings = (await agent_repository.list_mcp_binding_map(db, [agent.id]))[agent.id]
    agent.published = True
    agent.published_snapshot = agent_publication_snapshot(
        agent, bindings, mcp_bindings
    )
    agent.published_by_user_id = actor.id
    agent.published_at = utc_now()
    await agent_repository.save_agent(db, agent)
    await db.commit()
    return version
