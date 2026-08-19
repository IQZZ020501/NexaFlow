import asyncio
from copy import deepcopy
from collections.abc import AsyncIterator
from datetime import date, timedelta
import math
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.tool_runtime import preflight_tool_snapshot
from app.application.agent_child_runs import preflight_workflow_agent_snapshots
from app.application.agent_runs import cancel_run_tree, update_run_feedback
from app.application.workflow_uploads import resolve_workspace_workflow_files
from app.entities.agents import AgentRun
from app.entities.user import User
from app.entities.workflows import WorkflowRunDetail, WorkflowVersion
from app.infrastructure.agent_live_stream import (
    LIVE_EVENT_TYPES,
    AgentLiveStreamReader,
)
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import new_id, utc_now
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import workflow as workflow_repository
from app.infrastructure.session import get_session_factory
from app.schemas.workflow import (
    FormNodeConfig,
    WorkflowFormSubmitRequest,
    WorkflowNodeExecutionListResponse,
    WorkflowNodeExecutionResponse,
    WorkflowRunCreateRequest,
    WorkflowRunResponse,
    WorkflowPendingForm,
    WorkflowGraph,
)
from app.shareddomain.agents.permissions import require_agent_edit, require_agent_view
from app.shareddomain.agents.models import (
    agent_run_display_status,
    agent_run_generation,
    queued_agent_run_status,
)
from app.shareddomain.agents.services import ACTIVE_STATUS, get_agent_model
from app.shareddomain.workflows.services import (
    get_or_create_definition,
    get_workflow_agent,
    prepare_workflow_resources,
    validate_workflow_resources,
)
from app.shareddomain.tools.runtime import (
    tool_snapshot_from_payload,
    tool_snapshot_payload,
)
from app.shareddomain.workflows.engine import graph_hash
from app.shareddomain.workflows.resources import (
    canonicalize_workflow_snapshot_graph,
    load_workflow_agent_snapshots,
    load_workflow_resource_snapshot,
)
from app.tasks.agents import enqueue_agent_run

WORKFLOW_MAX_STEPS = 100
WORKFLOW_MAX_MODEL_TOKENS = 100_000
WORKFLOW_EVENT_PAGE_SIZE = 200


def workflow_run_to_response(
    run: AgentRun,
    detail: WorkflowRunDetail,
) -> WorkflowRunResponse:
    return WorkflowRunResponse(
        id=run.id,
        conversation_id=run.conversation_id,
        regenerated_from_run_id=run.regenerated_from_run_id,
        workspace_id=run.workspace_id,
        agent_id=run.agent_id,
        requested_by_user_id=run.requested_by_user_id,
        status=agent_run_display_status(run.status),
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
        pending_form=workflow_pending_form(run),
        feedback=run.feedback,
        feedback_updated_at=run.feedback_updated_at,
    )


async def regenerate_workflow_run_from_source(
    db: AsyncSession,
    source: AgentRun,
    detail: WorkflowRunDetail,
    actor: User,
    settings: Settings,
) -> WorkflowRunResponse:
    if source.status != "succeeded":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only a completed run can be regenerated.",
        )
    if await agent_repository.get_active_agent_run(
        db,
        source.agent_id,
        source.access_source,
        source.consumer_id,
        source.conversation_id,
    ) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This workflow conversation already has an active run.",
        )
    graph = WorkflowGraph.model_validate(detail.graph_snapshot)
    try:
        knowledge_base_ids, tool_snapshots = load_workflow_resource_snapshot(
            graph,
            detail.resource_snapshot,
            detail.resource_hash,
        )
        agent_snapshots = load_workflow_agent_snapshots(
            graph,
            detail.resource_snapshot,
            detail.resource_hash,
        )
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The source workflow snapshot is invalid.",
        ) from exc
    if knowledge_base_ids != source.knowledge_base_ids:
        raise HTTPException(status.HTTP_409_CONFLICT, "The source workflow snapshot changed.")
    for snapshot in tool_snapshots:
        if await preflight_tool_snapshot(
            db,
            snapshot,
            origin="workflow",
            workspace_id=source.workspace_id,
            execution_user_id=source.execution_user_id,
            access_source=source.access_source,
        ) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A source Workflow Tool is no longer executable.",
            )
    try:
        await preflight_workflow_agent_snapshots(
            db,
            source.workspace_id,
            agent_snapshots,
            execution_user_id=source.execution_user_id,
            access_source=source.access_source,
        )
        await get_agent_model(db, source.workspace_id, source.model_id)
    except (HTTPException, ValueError) as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A source Workflow resource is no longer available.",
        ) from exc
    form_submissions = {
        execution.node_id: deepcopy(execution.outputs["form_data"])
        for execution in await workflow_repository.list_node_executions(db, source.id)
        if execution.node_type == "form-node"
        and execution.status == "succeeded"
        and isinstance(execution.outputs.get("form_data"), dict)
    }
    run = AgentRun(
        workspace_id=source.workspace_id,
        agent_id=source.agent_id,
        requested_by_user_id=actor.id if source.access_source == "console" else None,
        execution_user_id=(
            actor.id if source.access_source == "console" else source.execution_user_id
        ),
        access_source=source.access_source,
        consumer_id=source.consumer_id,
        conversation_id=source.conversation_id,
        goal=source.goal,
        instructions=source.instructions,
        knowledge_base_ids=deepcopy(source.knowledge_base_ids),
        knowledge_query_mode=source.knowledge_query_mode,
        mcp_tools=deepcopy(source.mcp_tools),
        application_snapshot=deepcopy(source.application_snapshot),
        application_snapshot_hash=source.application_snapshot_hash,
        tool_snapshots=deepcopy(source.tool_snapshots),
        model_id=source.model_id,
        model_name=source.model_name,
        regenerated_from_run_id=source.id,
        configuration_source="draft",
        status=queued_agent_run_status(agent_run_generation("draft")),
        checkpoint_phase="workflow",
        checkpoint={"workflow_form_submissions": form_submissions},
        trace_id=new_id(),
        model_usage={},
    )
    new_detail = WorkflowRunDetail(
        workspace_id=detail.workspace_id,
        run_id=run.id,
        definition_id=detail.definition_id,
        definition_revision=detail.definition_revision,
        version_id=detail.version_id,
        version_number=detail.version_number,
        source=detail.source,
        graph_hash=detail.graph_hash,
        graph_snapshot=deepcopy(detail.graph_snapshot),
        resource_snapshot=deepcopy(detail.resource_snapshot),
        resource_hash=detail.resource_hash,
        inputs=deepcopy(detail.inputs),
        max_steps=detail.max_steps,
        max_model_tokens=detail.max_model_tokens,
        deadline_at=utc_now(),
    )
    try:
        run = await agent_repository.create_agent_run(db, run)
        await workflow_repository.create_run_detail(db, new_detail)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This workflow conversation already has an active run.",
        ) from exc
    await enqueue_agent_run(run.id, settings, generation="unified")
    current = await agent_repository.get_agent_run_by_id(db, run.id)
    current_detail = await workflow_repository.get_run_detail(db, run.id)
    assert current is not None and current_detail is not None
    return workflow_run_to_response(current, current_detail)


def workflow_pending_form(run: AgentRun) -> WorkflowPendingForm | None:
    value = (run.checkpoint or {}).get("workflow_form")
    if not isinstance(value, dict):
        return None
    return WorkflowPendingForm.model_validate(value)


def _validated_form_data(
    config: FormNodeConfig,
    submitted: dict[str, Any],
) -> dict[str, Any]:
    fields = {field.variable: field for field in config.form_field_list}
    if set(submitted) - set(fields):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Form contains unknown fields.",
        )
    result: dict[str, Any] = {}
    for variable, field in fields.items():
        value = submitted.get(variable)
        if field.is_required and (
            value is None or (isinstance(value, str) and not value.strip())
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Form field {variable} is required.",
            )
        if value is None or value == "":
            result[variable] = value
            continue
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Form field {variable} has an invalid value.",
            )
        text = str(value)
        if len(text) > 10000:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Form field {variable} is too long.",
            )
        if field.type == "select" and text not in field.optionList:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Form field {variable} has an invalid option.",
            )
        if field.type == "date":
            try:
                date.fromisoformat(text)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"Form field {variable} has an invalid date.",
                ) from exc
        if field.type == "number":
            try:
                number = float(text)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"Form field {variable} has an invalid number.",
                ) from exc
            if not math.isfinite(number):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"Form field {variable} has an invalid number.",
                )
            result[variable] = number
        else:
            result[variable] = text
    return result


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
    files: list[dict[str, Any]] | None = None,
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
    if version is None:
        parsed, tool_snapshots, resource_snapshot, resource_hash = (
            await prepare_workflow_resources(
                db,
                agent,
                graph,
                actor,
                workspace_role,
                binding_application_id=agent.id,
            )
        )
        knowledge_base_ids = resource_snapshot["knowledge_base_ids"]
    else:
        try:
            raw_tools = version.resource_snapshot.get("tools")
            if not isinstance(raw_tools, list):
                raise ValueError("Workflow resource snapshot is invalid.")
            parsed = canonicalize_workflow_snapshot_graph(
                WorkflowGraph.model_validate(graph),
                [tool_snapshot_from_payload(item) for item in raw_tools],
            )
            parsed = await validate_workflow_resources(
                db,
                agent,
                parsed,
                actor,
                workspace_role,
                default_model_id=default_model_id,
                binding_application_id=agent.id,
            )
            knowledge_base_ids, tool_snapshots = load_workflow_resource_snapshot(
                parsed,
                version.resource_snapshot,
                version.resource_hash,
            )
            agent_snapshots = load_workflow_agent_snapshots(
                parsed,
                version.resource_snapshot,
                version.resource_hash,
            )
            await preflight_workflow_agent_snapshots(
                db,
                workspace_id,
                agent_snapshots,
                execution_user_id=actor.id,
                access_source=access_source,
            )
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Workflow version must be republished before it can run.",
            ) from exc
        resource_snapshot = version.resource_snapshot
        resource_hash = version.resource_hash
    for snapshot in tool_snapshots:
        failure = await preflight_tool_snapshot(
            db,
            snapshot,
            origin="workflow",
            workspace_id=workspace_id,
            execution_user_id=actor.id,
            access_source=access_source,
        )
        if failure is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Workflow Tool configuration is no longer executable.",
            )
    if access_source == "console":
        files = await resolve_workspace_workflow_files(
            db,
            workspace_id,
            agent_id,
            actor,
            workspace_role,
            payload.file_ids,
            settings,
            extract_text=any(
                node.data.type == "document-extract-node" for node in parsed.nodes
            ),
        )
    elif payload.file_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "External workflow runs cannot use console upload ids.",
        )
    model = await get_agent_model(db, workspace_id, default_model_id)
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
        goal=payload.question,
        instructions=agent.instructions,
        knowledge_base_ids=knowledge_base_ids,
        knowledge_query_mode=agent.knowledge_query_mode,
        mcp_tools=[],
        application_snapshot={
            "schema_version": 1,
            "application_type": "workflow",
            "source": payload.source,
            "graph_hash": graph_hash(parsed),
            "resources": resource_snapshot,
        },
        tool_snapshots=[tool_snapshot_payload(item) for item in tool_snapshots],
        # WorkflowRunDetail carries the draft/published source. The shared Run
        # field selects the fenced v2 worker generation.
        configuration_source="draft",
        model_id=model.id,
        model_name=model.name,
        status=queued_agent_run_status(agent_run_generation("draft")),
        checkpoint_phase="workflow",
        trace_id=new_id(),
        model_usage={},
    )
    run_inputs: dict[str, Any] = {"question": payload.question}
    if files:
        run_inputs["files"] = files
        run_inputs["document"] = files
    run.application_snapshot_hash = graph_hash(run.application_snapshot)
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
        resource_snapshot=resource_snapshot,
        resource_hash=resource_hash,
        inputs=run_inputs,
        max_steps=WORKFLOW_MAX_STEPS,
        max_model_tokens=WORKFLOW_MAX_MODEL_TOKENS,
        # Reset from the worker's first claim so queue latency does not consume runtime.
        deadline_at=now,
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
    await enqueue_agent_run(run.id, settings, generation="unified")
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


async def cancel_workflow_run(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    run_id: str,
    actor: User,
    workspace_role: str | None,
) -> WorkflowRunResponse:
    await get_workflow_run(
        db,
        workspace_id,
        agent_id,
        run_id,
        actor,
        workspace_role,
    )
    if not await cancel_run_tree(db, run_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Workflow run is already finished.",
        )
    await db.commit()
    run = await agent_repository.get_agent_run_by_id(db, run_id)
    detail = await workflow_repository.get_run_detail(db, run_id)
    assert run is not None and detail is not None
    return workflow_run_to_response(run, detail)


async def regenerate_workflow_run(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    run_id: str,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> WorkflowRunResponse:
    source_response = await get_workflow_run(
        db,
        workspace_id,
        agent_id,
        run_id,
        actor,
        workspace_role,
    )
    del source_response
    source = await agent_repository.get_agent_run_by_id(db, run_id)
    detail = await workflow_repository.get_run_detail(db, run_id)
    if source is None or detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found.")
    return await regenerate_workflow_run_from_source(db, source, detail, actor, settings)


async def set_workflow_run_feedback(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    run_id: str,
    actor: User,
    workspace_role: str | None,
    value: str | None,
) -> WorkflowRunResponse:
    await get_workflow_run(db, workspace_id, agent_id, run_id, actor, workspace_role)
    run = await agent_repository.get_agent_run_by_id(db, run_id)
    detail = await workflow_repository.get_run_detail(db, run_id)
    if run is None or detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found.")
    updated = await update_run_feedback(db, run, value)
    return workflow_run_to_response(updated, detail)


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
        latest_versions_only=True,
    )
    details = {
        item.run_id: item
        for item in await workflow_repository.list_run_details_for_external_conversations(
            db, [run.id for run in runs]
        )
    }
    responses = []
    for run in runs:
        detail = details.get(run.id)
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


async def resume_workflow_form(
    db: AsyncSession,
    run: AgentRun,
    detail: WorkflowRunDetail,
    payload: WorkflowFormSubmitRequest,
    settings: Settings,
) -> WorkflowRunResponse:
    pending = workflow_pending_form(run)
    if agent_run_display_status(run.status) != "awaiting_input" or pending is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow is not awaiting form input.")
    if pending.runtime_node_id != payload.runtime_node_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow form node changed.")
    graph = WorkflowGraph.model_validate(detail.graph_snapshot)
    node = next(
        (
            item
            for item in graph.nodes
            if item.id == payload.runtime_node_id and item.data.type == "form-node"
        ),
        None,
    )
    if node is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow form node is unavailable.")
    form_data = _validated_form_data(
        FormNodeConfig.model_validate(node.data.config),
        payload.form_data,
    )
    checkpoint = dict(run.checkpoint or {})
    submissions = dict(checkpoint.get("workflow_form_submissions") or {})
    submissions[payload.runtime_node_id] = form_data
    checkpoint["workflow_form_submissions"] = submissions
    checkpoint.pop("workflow_form", None)
    now = utc_now()
    deadline_reset = await workflow_repository.reset_waiting_run_deadline(
        db,
        run.id,
        now + timedelta(seconds=settings.agent_run_timeout_seconds),
    )
    queued = await agent_repository.queue_agent_run_from_input(db, run.id, checkpoint)
    if not deadline_reset or not queued:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflow form was already submitted.")
    await db.commit()
    await enqueue_agent_run(run.id, settings, generation="unified")
    current = await agent_repository.get_agent_run_by_id(db, run.id)
    current_detail = await workflow_repository.get_run_detail(db, run.id)
    if current is None or current_detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found.")
    return workflow_run_to_response(current, current_detail)


async def submit_workflow_form(
    db: AsyncSession,
    workspace_id: str,
    agent_id: str,
    run_id: str,
    payload: WorkflowFormSubmitRequest,
    actor: User,
    workspace_role: str | None,
    settings: Settings,
) -> WorkflowRunResponse:
    await get_workflow_run(
        db,
        workspace_id,
        agent_id,
        run_id,
        actor,
        workspace_role,
    )
    run = await agent_repository.get_agent_run_by_id(db, run_id)
    detail = await workflow_repository.get_run_detail(db, run_id)
    if run is None or detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found.")
    return await resume_workflow_form(db, run, detail, payload, settings)


async def stream_workflow_run(
    run_id: str,
    settings: Settings,
    *,
    after: int = 0,
    live_after: str = "0-0",
) -> AsyncIterator[dict[str, Any]]:
    cursor = after
    live_cursor = live_after
    stopping_statuses = {"succeeded", "failed", "cancelled", "awaiting_input"}
    reader = AgentLiveStreamReader(settings, run_id)
    loop = asyncio.get_running_loop()
    next_database_poll = 0.0
    snapshot_sent = False
    try:
        while True:
            terminal_event: dict[str, Any] | None = None
            rows: list[Any] = []
            if loop.time() >= next_database_poll:
                async with get_session_factory()() as db:
                    run = await agent_repository.get_agent_run_by_id(db, run_id)
                    detail = await workflow_repository.get_run_detail(db, run_id)
                    rows = await agent_repository.list_agent_run_events(
                        db,
                        run_id,
                        after=cursor,
                        limit=WORKFLOW_EVENT_PAGE_SIZE,
                    )
                if run is None or detail is None:
                    return
                display_status = agent_run_display_status(run.status)
                if not snapshot_sent:
                    yield {
                        "type": "run",
                        "sequence": cursor,
                        "run": workflow_run_to_response(run, detail).model_dump(
                            mode="json"
                        ),
                    }
                    snapshot_sent = True
                next_database_poll = loop.time() + settings.agent_event_poll_seconds
                for row in rows:
                    assert row.id is not None
                    cursor = row.id
                    event = {**row.event, "sequence": cursor}
                    if event.get("type") in {
                        "complete",
                        "error",
                        "workflow_input_required",
                    }:
                        terminal_event = event
                    else:
                        yield event
                if (
                    display_status in stopping_statuses
                    and len(rows) == WORKFLOW_EVENT_PAGE_SIZE
                    and terminal_event is None
                ):
                    next_database_poll = 0.0
                    continue
                if display_status in stopping_statuses:
                    while reader.available:
                        live_events = await reader.read(live_cursor, 1)
                        if not live_events:
                            break
                        for live_sequence, event in live_events:
                            live_cursor = live_sequence
                            if event.get("type") in LIVE_EVENT_TYPES:
                                yield {**event, "live_sequence": live_cursor}
                    yield terminal_event or {
                        "type": (
                            "workflow_input_required"
                            if display_status == "awaiting_input"
                            else "complete" if display_status == "succeeded" else "error"
                        ),
                        "sequence": cursor,
                        "run": workflow_run_to_response(run, detail).model_dump(
                            mode="json"
                        ),
                    }
                    return

            wait_seconds = max(0.001, next_database_poll - loop.time())
            live_events = await reader.read(
                live_cursor,
                max(1, min(500, round(wait_seconds * 1000))),
            )
            for live_sequence, event in live_events:
                live_cursor = live_sequence
                if event.get("type") in LIVE_EVENT_TYPES:
                    yield {**event, "live_sequence": live_cursor}
            if not reader.available and not live_events:
                await asyncio.sleep(wait_seconds)
    finally:
        await reader.close()
