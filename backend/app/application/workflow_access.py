from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.agent_access import (
    ExternalAccessSource,
    PublishedAgentContext,
    get_published_workflow_context,
    get_workspace_published_workflow_context,
)
from app.application.workflow_runs import (
    create_workflow_run,
    regenerate_workflow_run_from_source,
    resume_workflow_form,
    stream_workflow_run,
    update_run_feedback,
    workflow_pending_form,
)
from app.application.workflow_uploads import (
    published_interaction_config,
    resolve_public_workflow_files,
)
from app.entities.agents import AgentRun
from app.entities.user import User
from app.infrastructure.agent_rate_limit import (
    AgentRateLimitExceeded,
    AgentRateLimitUnavailable,
    enforce_external_agent_rate_limit,
)
from app.infrastructure.config import Settings
from app.infrastructure.repositories import agent as agent_repository
from app.infrastructure.repositories import workflow as workflow_repository
from app.schemas.workflow import (
    ExternalWorkflowProgressEventResponse,
    ExternalWorkflowRunCreateRequest,
    ExternalWorkflowRunListResponse,
    ExternalWorkflowRunResponse,
    PublicWorkflowConversationListResponse,
    PublicWorkflowConversationResponse,
    PublicWorkflowProfileResponse,
    WorkflowApiDocumentationResponse,
    WorkflowFormSubmitRequest,
    WorkflowGraph,
    WorkflowRunCreateRequest,
)
from app.shareddomain.agents.models import agent_run_display_status


def _external_error(status_value: str) -> str | None:
    if status_value == "failed":
        return "Workflow run failed."
    if status_value == "cancelled":
        return "Workflow run was cancelled."
    return None


def _progress_id(event: dict[str, Any]) -> str:
    return f"workflow-node-{event.get('node_id', '')}"


def _external_run_response(
    run: AgentRun,
    detail,
    progress: list[ExternalWorkflowProgressEventResponse] | None = None,
) -> ExternalWorkflowRunResponse:
    """
    Build an external workflow run response from run details and optional progress events.
    
    Parameters:
    	run (AgentRun): The workflow run to serialize.
    	detail: The run's input and output details.
    	progress (list[ExternalWorkflowProgressEventResponse] | None): Progress events to include.
    
    Returns:
    	ExternalWorkflowRunResponse: The serialized run status, timestamps, inputs, outputs, progress, pending form, and feedback.
    """
    display_status = agent_run_display_status(run.status)
    return ExternalWorkflowRunResponse(
        id=run.id,
        conversation_id=run.conversation_id,
        regenerated_from_run_id=run.regenerated_from_run_id,
        inputs=detail.inputs,
        outputs=detail.outputs if display_status == "succeeded" else {},
        status=display_status,
        error=_external_error(display_status),
        progress=progress or [],
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        updated_at=run.updated_at,
        pending_form=workflow_pending_form(run),
        feedback=run.feedback,
        feedback_updated_at=run.feedback_updated_at,
    )


def _external_run_from_payload(payload: dict[str, Any]) -> ExternalWorkflowRunResponse:
    """
    Create an external workflow run response from a payload.
    
    Parameters:
        payload (dict[str, Any]): Run data containing identifiers, timestamps, status, inputs, outputs, and optional feedback or form information.
    
    Returns:
        ExternalWorkflowRunResponse: The external representation of the workflow run.
    """
    return ExternalWorkflowRunResponse(
        id=str(payload["id"]),
        conversation_id=str(payload.get("conversation_id") or ""),
        regenerated_from_run_id=payload.get("regenerated_from_run_id"),
        inputs=payload.get("inputs") or {},
        outputs=payload.get("outputs") or {},
        status=str(payload.get("status") or ""),
        error=_external_error(str(payload.get("status") or "")),
        progress=[],
        created_at=payload["created_at"],
        started_at=payload.get("started_at"),
        finished_at=payload.get("finished_at"),
        updated_at=payload["updated_at"],
        pending_form=payload.get("pending_form"),
        feedback=payload.get("feedback"),
        feedback_updated_at=payload.get("feedback_updated_at"),
    )


async def _rate_limit(settings: Settings, workflow_id: str, source: ExternalAccessSource, consumer_id: str) -> None:
    try:
        await enforce_external_agent_rate_limit(settings, workflow_id, source, consumer_id)
    except AgentRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Workflow run rate limit exceeded.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except AgentRateLimitUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Workflow run service is temporarily unavailable.",
        ) from exc


async def get_public_workflow_profile(
    db: AsyncSession,
    workflow_id: str,
    user: User,
) -> PublicWorkflowProfileResponse:
    context = await get_workspace_published_workflow_context(db, workflow_id, user)
    publication = context.publication
    return PublicWorkflowProfileResponse(
        id=context.agent.id,
        name=publication.name if publication else context.agent.name,
        description=publication.description if publication else context.agent.description,
        interaction_config=published_interaction_config(context),
    )


async def get_workflow_api_documentation(
    db: AsyncSession,
    context: PublishedAgentContext,
) -> WorkflowApiDocumentationResponse:
    return WorkflowApiDocumentationResponse(
        workflow_id=context.agent.id,
        workflow_name=(
            context.publication.name if context.publication else context.agent.name
        ),
        base_path=f"/api/v1/workflow-api/{context.agent.id}",
        interaction_config=published_interaction_config(context),
    )


async def _external_run(
    db: AsyncSession,
    workflow_id: str,
    run_id: str,
    source: ExternalAccessSource,
    consumer_id: str,
) -> tuple[AgentRun, Any]:
    await get_published_workflow_context(db, workflow_id)
    run = await agent_repository.get_agent_run_by_id(db, run_id)
    if (
        run is None
        or run.agent_id != workflow_id
        or run.access_source != source
        or run.consumer_id != consumer_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found.")
    detail = await workflow_repository.get_run_detail(db, run_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found.")
    return run, detail


async def create_external_workflow_run(
    db: AsyncSession,
    context: PublishedAgentContext,
    source: ExternalAccessSource,
    consumer_id: str,
    payload: ExternalWorkflowRunCreateRequest,
    actor: User,
    settings: Settings,
) -> ExternalWorkflowRunResponse:
    await _rate_limit(settings, context.agent.id, source, consumer_id)
    if source == "api" and payload.file_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "API workflow runs cannot use public upload ids.",
        )
    version = await workflow_repository.get_version(
        db, context.agent.workspace_id, context.agent.id
    )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Published workflow not found.")
    files = (
        await resolve_public_workflow_files(
            db,
            context,
            consumer_id,
            payload.file_ids,
            settings,
            extract_text=any(
                node.data.type == "document-extract-node"
                for node in WorkflowGraph.model_validate(version.graph).nodes
            ),
        )
        if source == "public"
        else []
    )
    run = await create_workflow_run(
        db,
        context.agent.workspace_id,
        context.agent.id,
        WorkflowRunCreateRequest(
            question=payload.question,
            source="published",
            version_number=version.version_number,
        ),
        actor,
        context.workspace.membership_role,
        settings,
        access_source=source,
        consumer_id=consumer_id,
        conversation_id=payload.conversation_id,
        files=files,
    )
    return ExternalWorkflowRunResponse(
        id=run.id,
        conversation_id=run.conversation_id,
        inputs=run.inputs,
        outputs=run.outputs,
        status=run.status,
        error=_external_error(run.status),
        progress=[],
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        updated_at=run.updated_at,
    )


async def get_external_workflow_run(
    db: AsyncSession,
    workflow_id: str,
    run_id: str,
    source: ExternalAccessSource,
    consumer_id: str,
) -> ExternalWorkflowRunResponse:
    """
    Retrieve the current state and progress of an externally accessible workflow run.
    
    Parameters:
    	workflow_id (str): The workflow identifier.
    	run_id (str): The workflow run identifier.
    	source (ExternalAccessSource): The access source associated with the run.
    	consumer_id (str): The consumer identifier associated with the run.
    
    Returns:
    	ExternalWorkflowRunResponse: The run status, outputs, pending forms, feedback, and node progress.
    """
    run, detail = await _external_run(db, workflow_id, run_id, source, consumer_id)
    executions = await workflow_repository.list_node_executions(db, run.id)
    return _external_run_response(
        run,
        detail,
        [
            ExternalWorkflowProgressEventResponse(
                id=execution.id,
                node_id=execution.node_id,
                node_type=execution.node_type,
                status=execution.status,
                error=("Workflow node failed." if execution.status == "failed" else None),
                duration_ms=execution.duration_ms,
            )
            for execution in executions
        ],
    )


async def regenerate_external_workflow_run(
    db: AsyncSession,
    workflow_id: str,
    run_id: str,
    source: ExternalAccessSource,
    consumer_id: str,
    actor: User,
    settings: Settings,
) -> ExternalWorkflowRunResponse:
    """
    Regenerates a public external workflow run.
    
    Parameters:
        workflow_id (str): Identifier of the workflow.
        run_id (str): Identifier of the run to regenerate.
        source (ExternalAccessSource): Access source for the run.
        consumer_id (str): Identifier of the consumer requesting the regeneration.
        actor (User): User performing the regeneration.
        settings (Settings): Application settings used during regeneration.
    
    Returns:
        ExternalWorkflowRunResponse: The regenerated workflow run.
    """
    if source != "public":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found.")
    run, detail = await _external_run(db, workflow_id, run_id, source, consumer_id)
    regenerated = await regenerate_workflow_run_from_source(
        db, run, detail, actor, settings
    )
    return _external_run_from_payload(regenerated.model_dump(mode="json"))


async def set_external_workflow_run_feedback(
    db: AsyncSession,
    workflow_id: str,
    run_id: str,
    source: ExternalAccessSource,
    consumer_id: str,
    value: str | None,
) -> ExternalWorkflowRunResponse:
    """
    Update the feedback associated with a public external workflow run.
    
    Parameters:
        value (str | None): Feedback text, or `None` to clear the existing feedback.
    
    Returns:
        ExternalWorkflowRunResponse: The updated external workflow run.
    
    Raises:
        HTTPException: If the run is not public or cannot be found.
    """
    if source != "public":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found.")
    run, detail = await _external_run(db, workflow_id, run_id, source, consumer_id)
    updated = await update_run_feedback(db, run, value)
    return _external_run_response(updated, detail)


async def submit_external_workflow_form(
    db: AsyncSession,
    workflow_id: str,
    run_id: str,
    source: ExternalAccessSource,
    consumer_id: str,
    payload: WorkflowFormSubmitRequest,
    settings: Settings,
) -> ExternalWorkflowRunResponse:
    """
    Resume an external workflow run with submitted form data.
    
    Parameters:
        payload (WorkflowFormSubmitRequest): Form data submitted for the workflow run.
    
    Returns:
        ExternalWorkflowRunResponse: The resumed workflow run.
    """
    run, detail = await _external_run(db, workflow_id, run_id, source, consumer_id)
    resumed = await resume_workflow_form(db, run, detail, payload, settings)
    return _external_run_from_payload(resumed.model_dump(mode="json"))


async def list_external_workflow_runs(
    db: AsyncSession,
    workflow_id: str,
    source: ExternalAccessSource,
    consumer_id: str,
    limit: int,
    offset: int,
    conversation_id: str | None = None,
) -> ExternalWorkflowRunListResponse:
    """
    List the latest external workflow runs available to a consumer.
    
    Parameters:
        workflow_id (str): Identifier of the workflow.
        source (ExternalAccessSource): External access source used to access the runs.
        consumer_id (str): Identifier of the consumer whose runs are listed.
        limit (int): Maximum number of runs to include.
        offset (int): Number of runs to skip before listing results.
        conversation_id (str | None): Optional conversation identifier used to filter runs.
    
    Returns:
        ExternalWorkflowRunListResponse: Paginated workflow runs and the total number of matching runs.
    """
    await get_published_workflow_context(db, workflow_id)
    runs = await agent_repository.list_agent_runs(
        db,
        workflow_id,
        source,
        consumer_id,
        limit,
        offset,
        conversation_id=conversation_id,
        latest_versions_only=True,
    )
    total = await agent_repository.count_agent_runs(
        db,
        workflow_id,
        access_source=source,
        consumer_id=consumer_id,
        conversation_id=conversation_id,
        latest_versions_only=True,
    )
    details = {
        item.run_id: item
        for item in await workflow_repository.list_run_details_for_external_conversations(
            db, [run.id for run in runs]
        )
    }
    items = []
    for run in runs:
        detail = details.get(run.id)
        if detail is not None:
            items.append(_external_run_response(run, detail))
    return ExternalWorkflowRunListResponse(
        items=items, total=total, offset=offset, limit=limit
    )


async def list_public_workflow_conversations(
    db: AsyncSession,
    workflow_id: str,
    consumer_id: str,
) -> PublicWorkflowConversationListResponse:
    await get_published_workflow_context(db, workflow_id)
    rows = await agent_repository.list_consumer_conversations(
        db, workflow_id, "public", consumer_id
    )
    details = {
        item.run_id: item
        for item in await workflow_repository.list_run_details_for_external_conversations(
            db, [row.run_id for row in rows]
        )
    }
    items = []
    for row in rows:
        detail = details.get(row.run_id)
        if detail is None:
            continue
        items.append(
            PublicWorkflowConversationResponse(
                conversation_id=row.conversation_id,
                inputs=detail.inputs,
                outputs=(
                    detail.outputs
                    if agent_run_display_status(row.status) == "succeeded"
                    else {}
                ),
                status=agent_run_display_status(row.status),
                run_count=row.run_count,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return PublicWorkflowConversationListResponse(items=items)


async def stream_external_workflow_run(
    run_id: str,
    settings: Settings,
    *,
    after: int = 0,
    live_after: str = "0-0",
) -> AsyncIterator[dict[str, Any]]:
    async for event in stream_workflow_run(
        run_id,
        settings,
        after=after,
        live_after=live_after,
    ):
        event_type = event.get("type")
        if event_type == "answer_delta":
            yield {
                **{
                    key: event[key]
                    for key in ("live_sequence", "stream_epoch")
                    if key in event
                },
                "type": "answer_delta",
                "node_id": str(event.get("node_id") or ""),
                "delta": str(event.get("delta") or ""),
            }
        elif event_type in {
            "run",
            "complete",
            "error",
            "workflow_input_required",
        } and isinstance(event.get("run"), dict):
            yield {
                **{key: event[key] for key in ("type", "sequence") if key in event},
                "run": _external_run_from_payload(event["run"]).model_dump(mode="json"),
            }
        elif event_type == "workflow_node_started":
            yield {
                "type": "progress",
                "sequence": event.get("sequence", 0),
                "event": {
                    "id": _progress_id(event),
                    "node_id": str(event.get("node_id") or ""),
                    "node_type": str(event.get("node_type") or "variable"),
                    "status": "running",
                    "error": None,
                    "duration_ms": None,
                },
            }
        elif event_type == "workflow_node":
            yield {
                "type": "progress",
                "sequence": event.get("sequence", 0),
                "event": {
                    "id": _progress_id(event),
                    "node_id": str(event.get("node_id") or ""),
                    "node_type": str(event.get("node_type") or "variable"),
                    "status": event.get("status", "failed"),
                    "error": (
                        "Workflow node failed."
                        if event.get("status") == "failed"
                        else None
                    ),
                    "duration_ms": event.get("duration_ms"),
                },
            }
