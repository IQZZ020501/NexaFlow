from collections.abc import AsyncIterator
from typing import Annotated
import json

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    WorkspaceContext,
    Settings,
    get_db,
    get_settings,
    get_workspace_context_from_path,
)
from app.application.workflows import (
    create_workflow_run,
    get_workflow_definition,
    get_workflow_run,
    list_workflow_node_executions,
    list_workflow_runs,
    list_workflow_versions,
    publish_workflow_definition,
    restore_workflow_version,
    update_workflow_definition,
    validate_workflow_definition,
    stream_workflow_run,
    submit_workflow_form,
    upload_workspace_workflow_files,
)
from app.schemas.workflow import (
    WorkflowDefinitionResponse,
    WorkflowDefinitionUpdateRequest,
    WorkflowNodeExecutionListResponse,
    WorkflowRunCreateRequest,
    WorkflowFormSubmitRequest,
    WorkflowRunResponse,
    WorkflowValidationRequest,
    WorkflowValidationResponse,
    WorkflowVersionListResponse,
    WorkflowVersionRestoreRequest,
    WorkflowVersionResponse,
    WorkflowUploadResponse,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/workflows",
    tags=["workflows"],
)


@router.get("/{agent_id}/definition", response_model=WorkflowDefinitionResponse)
async def get_definition(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowDefinitionResponse:
    return await get_workflow_definition(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
    )


@router.put("/{agent_id}/definition", response_model=WorkflowDefinitionResponse)
async def put_definition(
    agent_id: str,
    payload: WorkflowDefinitionUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowDefinitionResponse:
    return await update_workflow_definition(
        db,
        context.workspace.id,
        agent_id,
        payload,
        context.user,
        context.membership_role,
    )


@router.post(
    "/{agent_id}/validate",
    response_model=WorkflowValidationResponse,
)
async def validate_definition(
    agent_id: str,
    payload: WorkflowValidationRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowValidationResponse:
    return await validate_workflow_definition(
        db,
        context.workspace.id,
        agent_id,
        payload.graph,
        context.user,
        context.membership_role,
    )


@router.post(
    "/{agent_id}/publish",
    response_model=WorkflowVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_definition(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowVersionResponse:
    return await publish_workflow_definition(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
    )


@router.get("/{agent_id}/versions", response_model=WorkflowVersionListResponse)
async def get_versions(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowVersionListResponse:
    return await list_workflow_versions(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
    )


@router.post(
    "/{agent_id}/versions/{version_number}/restore",
    response_model=WorkflowDefinitionResponse,
)
async def restore_version(
    agent_id: str,
    version_number: Annotated[int, Path(ge=1)],
    payload: WorkflowVersionRestoreRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowDefinitionResponse:
    return await restore_workflow_version(
        db,
        context.workspace.id,
        agent_id,
        version_number,
        payload.expected_revision,
        context.user,
        context.membership_role,
    )


@router.get("/{agent_id}/runs", response_model=list[WorkflowRunResponse])
async def get_runs(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WorkflowRunResponse]:
    return await list_workflow_runs(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
        limit,
        offset,
    )


@router.post(
    "/{agent_id}/uploads",
    response_model=list[WorkflowUploadResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_workspace_workflow_attachments(
    agent_id: str,
    files: Annotated[list[UploadFile], File()],
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkflowUploadResponse]:
    return await upload_workspace_workflow_files(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
        files,
        settings,
    )


@router.post(
    "/{agent_id}/runs",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_run(
    agent_id: str,
    payload: WorkflowRunCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowRunResponse:
    return await create_workflow_run(
        db,
        context.workspace.id,
        agent_id,
        payload,
        context.user,
        context.membership_role,
        settings,
    )


@router.get("/{agent_id}/runs/{run_id}", response_model=WorkflowRunResponse)
async def get_run(
    agent_id: str,
    run_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowRunResponse:
    return await get_workflow_run(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        context.user,
        context.membership_role,
    )


@router.post(
    "/{agent_id}/runs/{run_id}/form",
    response_model=WorkflowRunResponse,
)
async def post_run_form(
    agent_id: str,
    run_id: str,
    payload: WorkflowFormSubmitRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowRunResponse:
    return await submit_workflow_form(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        payload,
        context.user,
        context.membership_role,
        settings,
    )


@router.get(
    "/{agent_id}/runs/{run_id}/nodes",
    response_model=WorkflowNodeExecutionListResponse,
)
async def get_run_nodes(
    agent_id: str,
    run_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkflowNodeExecutionListResponse:
    return await list_workflow_node_executions(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        context.user,
        context.membership_role,
    )


@router.get(
    "/{agent_id}/runs/{run_id}/stream",
    response_class=StreamingResponse,
)
async def reconnect_run(
    agent_id: str,
    run_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    after: Annotated[int, Query(ge=0)] = 0,
    live_after: Annotated[str, Query(pattern=r"^[0-9]+-[0-9]+$")] = "0-0",
) -> StreamingResponse:
    await get_workflow_run(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        context.user,
        context.membership_role,
    )
    await db.rollback()

    async def encode_events() -> AsyncIterator[bytes]:
        async for event in stream_workflow_run(
            run_id,
            settings,
            after=after,
            live_after=live_after,
        ):
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode()

    return StreamingResponse(
        encode_events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
