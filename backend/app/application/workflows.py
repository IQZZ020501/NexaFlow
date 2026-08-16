from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.user import User
from app.infrastructure.repositories import workflow as workflow_repository
from app.schemas.workflow import (
    WorkflowDefinitionResponse,
    WorkflowDefinitionUpdateRequest,
    WorkflowGraph,
    WorkflowValidationResponse,
    WorkflowVersionListResponse,
    WorkflowVersionResponse,
)
from app.shareddomain.agents.permissions import require_agent_edit, require_agent_view
from app.shareddomain.workflows.engine import graph_hash
from app.shareddomain.workflows.services import (
    definition_to_response,
    get_or_create_definition,
    get_workflow_agent,
    publish_definition,
    save_definition,
    validate_workflow_resources,
    version_to_response,
)
from app.application.workflow_runs import (
    create_workflow_run,
    get_workflow_run,
    list_workflow_node_executions,
    list_workflow_runs,
    submit_workflow_form,
    stream_workflow_run,
)
from app.application.workflow_access import (
    create_external_workflow_run,
    get_external_workflow_run,
    get_public_workflow_profile,
    get_workflow_api_documentation,
    list_external_workflow_runs,
    list_public_workflow_conversations,
    stream_external_workflow_run,
    submit_external_workflow_form,
)
from app.application.workflow_uploads import (
    upload_public_workflow_files,
    upload_workspace_workflow_files,
)

__all__ = [
    "create_external_workflow_run",
    "create_workflow_run",
    "get_external_workflow_run",
    "get_public_workflow_profile",
    "get_workflow_api_documentation",
    "get_workflow_definition",
    "get_workflow_run",
    "list_external_workflow_runs",
    "list_public_workflow_conversations",
    "list_workflow_node_executions",
    "list_workflow_runs",
    "list_workflow_versions",
    "publish_workflow_definition",
    "restore_workflow_version",
    "stream_external_workflow_run",
    "stream_workflow_run",
    "submit_external_workflow_form",
    "submit_workflow_form",
    "upload_public_workflow_files",
    "upload_workspace_workflow_files",
    "update_workflow_definition",
    "validate_workflow_definition",
]


async def get_workflow_definition(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
) -> WorkflowDefinitionResponse:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    definition = await get_or_create_definition(db, agent, actor, workspace_role)
    return definition_to_response(definition)


async def validate_workflow_definition(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    graph: WorkflowGraph,
    actor: User,
    workspace_role: str | None,
) -> WorkflowValidationResponse:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    require_agent_edit(agent, actor, workspace_role)
    parsed = await validate_workflow_resources(
        db, agent, graph, actor, workspace_role
    )
    return WorkflowValidationResponse(graph_hash=graph_hash(parsed))


async def update_workflow_definition(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    payload: WorkflowDefinitionUpdateRequest,
    actor: User,
    workspace_role: str | None,
) -> WorkflowDefinitionResponse:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    require_agent_edit(agent, actor, workspace_role)
    definition = await get_or_create_definition(db, agent, actor, workspace_role)
    updated = await save_definition(
        db,
        agent,
        definition,
        payload.graph,
        payload.expected_revision,
        actor,
        workspace_role,
    )
    return definition_to_response(updated)


async def publish_workflow_definition(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
) -> WorkflowVersionResponse:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    require_agent_edit(agent, actor, workspace_role)
    if workspace_role != "admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Workspace admin required to publish workflows.",
        )
    await get_or_create_definition(db, agent, actor, workspace_role)
    return version_to_response(
        await publish_definition(db, agent, actor, workspace_role)
    )


async def list_workflow_versions(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
) -> WorkflowVersionListResponse:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    await require_agent_view(db, agent, actor, workspace_role)
    items = await workflow_repository.list_versions(db, workspace_id, agent_id)
    return WorkflowVersionListResponse(
        items=[version_to_response(item) for item in items]
    )


async def restore_workflow_version(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    version_number: int,
    expected_revision: int,
    actor: User,
    workspace_role: str | None,
) -> WorkflowDefinitionResponse:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    require_agent_edit(agent, actor, workspace_role)
    definition = await get_or_create_definition(db, agent, actor, workspace_role)
    version = await workflow_repository.get_version(
        db, workspace_id, agent_id, version_number
    )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow version not found.")
    graph = await validate_workflow_resources(
        db,
        agent,
        version.graph,
        actor,
        workspace_role,
    )
    updated = await save_definition(
        db,
        agent,
        definition,
        graph,
        expected_revision,
        actor,
        workspace_role,
    )
    return definition_to_response(updated)
