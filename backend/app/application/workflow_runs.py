import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.agents import AgentRun
from app.entities.user import User
from app.entities.workflows import WorkflowRunDetail, WorkflowVersion
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import workflow as workflow_repository
from app.infrastructure.session import get_session_factory
from app.schemas.workflow import (
    WorkflowNodeExecutionListResponse,
    WorkflowNodeExecutionResponse,
    WorkflowRunCreateRequest,
    WorkflowRunResponse,
)
from app.shareddomain.agents.permissions import require_agent_edit, require_agent_view
from app.shareddomain.agents.services import ACTIVE_STATUS, get_agent_model
from app.shareddomain.workflows.services import (
    get_or_create_definition,
    get_workflow_agent,
    validate_workflow_resources,
)
from app.tasks.agents import enqueue_agent_run

WORKFLOW_MAX_STEPS = 100
WORKFLOW_MAX_MODEL_TOKENS = 100_000
WORKFLOW_MAX_INPUT_BYTES = 128 * 1024
WORKFLOW_EVENT_PAGE_SIZE = 200


def workflow_run_to_response(
    run: AgentRun,
    detail: WorkflowRunDetail,
) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=run.id,
        conversation_id=run.conversation_id,
        workspace_id=run.workspace_id,
        agent_id=run.agent_id,
        requested_by_user_id=run.requested_by_user_id,
        status=run.status,
        source=detail.source,
        definition_revision=detail.definition_revision,
        version_number=detail.version_number,
        graph_hash=detail.graph_hash,
        inputs=detail.inputs,
        outputs=detail.outputs,
        max_steps=detail.max_steps,
        max_model_tokens=detail.max_model_tokens,
        step_count=detail.step_count,
        token_usage=detail.token_usage,
        last_error=run.last_error,
        trace_id=run.trace_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def node_execution_to_response(item) -> WorkflowNodeExecutionResponse:
    return WorkflowNodeExecutionResponse(
        id=item.id,
        run_id=item.run_id,
        node_id=item.node_id,
        node_type=item.node_type,
        status=item.status,
        sequence=item.sequence,
        inputs=item.inputs,
        outputs=item.outputs,
        model_usage=item.model_usage,
        error=item.error,
        started_at=item.started_at,
        finished_at=item.finished_at,
        duration_ms=item.duration_ms,
    )


async def _version_for_run(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    payload: WorkflowRunCreateRequest,
) -> WorkflowVersion | None:
    if payload.source == "draft":
        if payload.version_number is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Draft runs cannot select a published version.",
            )
        return None
    version = await workflow_repository.get_version(
        db,
        workspace_id,
        agent_id,
        payload.version_number,
    )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow version not found.")
    return version


async def create_workflow_run(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    payload: WorkflowRunCreateRequest,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
    *,
    access_source: str = "console",
    consumer_id: str | None = None,
    conversation_id: str | None = None,
) -> WorkflowRunResponse:
    if access_source not in {"console", "public", "api"}:
        raise ValueError("Invalid workflow run access source.")
    if access_source != "console" and payload.source != "published":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "External workflow runs must use a published version.",
        )
    if access_source != "console" and not consumer_id:
        raise ValueError("External workflow runs require a consumer id.")
    encoded_inputs = json.dumps(payload.inputs, ensure_ascii=False, separators=(",", ":"))
    if len(encoded_inputs.encode()) > WORKFLOW_MAX_INPUT_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Workflow inputs exceed 128 KiB.",
        )
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    if payload.source == "draft" and access_source == "console":
        require_agent_edit(agent, actor, workspace_role)
    else:
        await require_agent_view(db, agent, actor, workspace_role)
    if agent.status != ACTIVE_STATUS:
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow is disabled.")
    definition = await get_or_create_definition(db, agent, actor, workspace_role)
    version = await _version_for_run(db, workspace_id, agent_id, payload)
    graph = version.graph if version is not None else definition.graph
    default_model_id = version.default_model_id if version is not None else agent.model_id
    parsed = await validate_workflow_resources(
        db,
        agent,
        graph,
        default_model_id=default_model_id,
    )
    model = await get_agent_model(db, workspace_id, default_model_id)
    knowledge_bindings = (await agent_repository.list_binding_map(db, [agent.id]))[
        agent.id
    ]
    mcp_bindings = (await agent_repository.list_mcp_binding_map(db, [agent.id]))[
        agent.id
    ]
    now = utc_now()
    run_conversation_id = conversation_id or new_id()
    if conversation_id and await agent_repository.get_active_agent_run(
        db,
        agent.id,
        access_source,
        consumer_id or actor.id,
        conversation_id,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This workflow conversation already has an active run.",
        )
    run = AgentRun(
        workspace_id=workspace_id,
        agent_id=agent.id,
        requested_by_user_id=actor.id if access_source == "console" else None,
        execution_user_id=actor.id,
        access_source=access_source,
        consumer_id=consumer_id or actor.id,
        conversation_id=run_conversation_id,
        goal=encoded_inputs[:4000],
        instructions=agent.instructions,
        knowledge_base_ids=knowledge_bindings,
        knowledge_query_mode=agent.knowledge_query_mode,
        mcp_tools=mcp_bindings,
        model_id=model.id,
        model_name=model.name,
        status="queued",
        checkpoint_phase="workflow",
        trace_id=new_id(),
        model_usage={},
    )
    detail = WorkflowRunDetail(
        workspace_id=workspace_id,
        definition_id=definition.id,
        definition_revision=(
            version.definition_revision if version is not None else definition.revision
        ),
        version_id=version.id if version is not None else None,
        version_number=version.version_number if version is not None else None,
        source=payload.source,
        graph_hash=(version.graph_hash if version is not None else definition.graph_hash),
        graph_snapshot=parsed.model_dump(by_alias=True, mode="json"),
        inputs=payload.inputs,
        max_steps=WORKFLOW_MAX_STEPS,
        max_model_tokens=WORKFLOW_MAX_MODEL_TOKENS,
        deadline_at=now + timedelta(seconds=settings.agent_run_timeout_seconds),
    )
    try:
        run = await agent_repository.create_agent_run(db, run)
        detail.run_id = run.id
        detail = await workflow_repository.create_run_detail(db, detail)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This workflow conversation already has an active run.",
        ) from exc
    await enqueue_agent_run(run.id, settings)
    current = await agent_repository.get_agent_run_by_id(db, run.id)
    current_detail = await workflow_repository.get_run_detail(db, run.id)
    assert current is not None and current_detail is not None
    return workflow_run_to_response(current, current_detail)


async def get_workflow_run(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    run_id: str,
    actor: User,
    workspace_role: str | None,
) -> WorkflowRunResponse:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    await require_agent_view(db, agent, actor, workspace_role)
    run = await agent_repository.get_agent_run_by_id(db, run_id)
    detail = await workflow_repository.get_run_detail(db, run_id)
    if (
        run is None
        or detail is None
        or run.workspace_id != workspace_id
        or run.agent_id != agent_id
        or run.access_source != "console"
        or run.consumer_id != actor.id
        or run.requested_by_user_id != actor.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found.")
    return workflow_run_to_response(run, detail)


async def list_workflow_runs(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    actor: User,
    workspace_role: str | None,
    limit: int,
    offset: int,
) -> list[WorkflowRunResponse]:
    agent = await get_workflow_agent(db, workspace_id, agent_id)
    await require_agent_view(db, agent, actor, workspace_role)
    runs = await agent_repository.list_agent_runs(
        db,
        agent_id,
        "console",
        actor.id,
        limit,
        offset,
    )
    responses = []
    for run in runs:
        detail = await workflow_repository.get_run_detail(db, run.id)
        if detail is not None:
            responses.append(workflow_run_to_response(run, detail))
    return responses


async def list_workflow_node_executions(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    run_id: str,
    actor: User,
    workspace_role: str | None,
) -> WorkflowNodeExecutionListResponse:
    await get_workflow_run(
        db, workspace_id, agent_id, run_id, actor, workspace_role
    )
    items = await workflow_repository.list_node_executions(db, run_id)
    return WorkflowNodeExecutionListResponse(
        items=[node_execution_to_response(item) for item in items]
    )


async def stream_workflow_run(
    run_id: str,
    settings: Settings,
    *,
    after: int = 0,
) -> AsyncIterator[dict[str, Any]]:
    cursor = after
    snapshot_sent = False
    terminal = {"succeeded", "failed", "cancelled"}
    while True:
        async with get_session_factory()() as db:
            run = await agent_repository.get_agent_run_by_id(db, run_id)
            detail = await workflow_repository.get_run_detail(db, run_id)
            rows = await agent_repository.list_agent_run_events(
                db, run_id, after=cursor, limit=WORKFLOW_EVENT_PAGE_SIZE
            )
        if run is None or detail is None:
            return
        if not snapshot_sent:
            yield {
                "type": "run",
                "sequence": cursor,
                "run": workflow_run_to_response(run, detail).model_dump(mode="json"),
            }
            snapshot_sent = True
        terminal_event = None
        for row in rows:
            assert row.id is not None
            cursor = row.id
            event = {**row.event, "sequence": cursor}
            if event.get("type") in {"complete", "error"}:
                terminal_event = event
            else:
                yield event
        if run.status in terminal and len(rows) == WORKFLOW_EVENT_PAGE_SIZE:
            continue
        if run.status in terminal:
            yield terminal_event or {
                "type": "complete" if run.status == "succeeded" else "error",
                "sequence": cursor,
                "run": workflow_run_to_response(run, detail).model_dump(mode="json"),
            }
            return
        await asyncio.sleep(settings.agent_event_poll_seconds)
