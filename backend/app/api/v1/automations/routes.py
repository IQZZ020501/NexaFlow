"""HTTP routers for workspace automations and inbound webhooks."""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from app.api.deps import (
    AppSettingsDep,
    DbSessionDep,
    WorkspaceContext,
    get_workspace_context_from_path,
)
from app.application.automations import (
    cancel_automation_execution,
    create_automation,
    execute_automation_manually,
    get_automation_detail,
    get_automation_execution_detail,
    list_automation_executions,
    list_automations,
    pause_automation,
    receive_webhook_trigger,
    resolve_automation_tool_approval,
    resume_automation,
    rotate_automation_webhook_secret,
    submit_automation_workflow_form,
    update_automation,
)
from app.schemas.automations import (
    AutomationCreateRequest,
    AutomationCreateResponse,
    AutomationExecuteRequest,
    AutomationExecutionDetailResponse,
    AutomationExecutionListResponse,
    AutomationListResponse,
    AutomationResponse,
    AutomationToolApprovalRequest,
    AutomationUpdateRequest,
    AutomationWebhookReceiptResponse,
    AutomationWebhookSecretRotateResponse,
)
from app.schemas.workflows.contracts import WorkflowFormSubmitRequest

MAX_WEBHOOK_CONTENT_LENGTH_HEADER = 262_144

WorkspaceContextPathDep = Annotated[
    WorkspaceContext, Depends(get_workspace_context_from_path)
]

router = APIRouter(
    prefix="/workspaces/{workspace_id}/automations",
    tags=["automations"],
)

hooks_router = APIRouter(
    prefix="/hooks/automations",
    tags=["automations"],
)


@router.get("", response_model=AutomationListResponse)
async def list_workspace_automations(
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    response: Response,
    target_app_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AutomationListResponse:
    result = await list_automations(
        db,
        context.workspace.id,
        context.user,
        target_app_id=target_app_id,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(result.total)
    return result


@router.post(
    "",
    response_model=AutomationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_automation(
    payload: AutomationCreateRequest,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
) -> AutomationCreateResponse:
    return await create_automation(
        db,
        context.workspace.id,
        payload,
        context.user,
        settings,
    )


@router.get("/{automation_id}", response_model=AutomationResponse)
async def get_workspace_automation(
    automation_id: str,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
) -> AutomationResponse:
    return await get_automation_detail(
        db,
        context.workspace.id,
        automation_id,
        context.user,
    )


@router.patch("/{automation_id}", response_model=AutomationResponse)
async def update_workspace_automation(
    automation_id: str,
    payload: AutomationUpdateRequest,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
) -> AutomationResponse:
    return await update_automation(
        db,
        context.workspace.id,
        automation_id,
        payload,
        context.user,
        settings,
    )


@router.post("/{automation_id}/pause", response_model=AutomationResponse)
async def pause_workspace_automation(
    automation_id: str,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
) -> AutomationResponse:
    return await pause_automation(
        db,
        context.workspace.id,
        automation_id,
        context.user,
    )


@router.post("/{automation_id}/resume", response_model=AutomationResponse)
async def resume_workspace_automation(
    automation_id: str,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
) -> AutomationResponse:
    return await resume_automation(
        db,
        context.workspace.id,
        automation_id,
        context.user,
        settings,
    )


@router.post(
    "/{automation_id}/webhook-secret/rotate",
    response_model=AutomationWebhookSecretRotateResponse,
)
async def rotate_workspace_automation_webhook_secret(
    automation_id: str,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
) -> AutomationWebhookSecretRotateResponse:
    return await rotate_automation_webhook_secret(
        db,
        context.workspace.id,
        automation_id,
        context.user,
        settings,
    )


@router.post(
    "/{automation_id}/execute",
    response_model=AutomationExecutionDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_workspace_automation(
    automation_id: str,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
    payload: AutomationExecuteRequest | None = None,
) -> AutomationExecutionDetailResponse:
    return await execute_automation_manually(
        db,
        context.workspace.id,
        automation_id,
        payload.request_id if payload is not None else None,
        context.user,
        context.membership_role,
        settings,
    )


@router.get(
    "/{automation_id}/executions",
    response_model=AutomationExecutionListResponse,
)
async def list_workspace_automation_executions(
    automation_id: str,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AutomationExecutionListResponse:
    result = await list_automation_executions(
        db,
        context.workspace.id,
        automation_id,
        context.user,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(result.total)
    return result


@router.get(
    "/{automation_id}/executions/{execution_id}",
    response_model=AutomationExecutionDetailResponse,
)
async def get_workspace_automation_execution(
    automation_id: str,
    execution_id: str,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
) -> AutomationExecutionDetailResponse:
    return await get_automation_execution_detail(
        db,
        context.workspace.id,
        automation_id,
        execution_id,
        context.user,
        context.membership_role,
        settings,
    )


@router.post(
    "/{automation_id}/executions/{execution_id}/cancel",
    response_model=AutomationExecutionDetailResponse,
)
async def cancel_workspace_automation_execution(
    automation_id: str,
    execution_id: str,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
) -> AutomationExecutionDetailResponse:
    return await cancel_automation_execution(
        db,
        context.workspace.id,
        automation_id,
        execution_id,
        context.user,
        context.membership_role,
        settings,
    )


@router.post(
    "/{automation_id}/executions/{execution_id}/tool-calls/{call_id}/approval",
    response_model=AutomationExecutionDetailResponse,
)
async def resolve_workspace_automation_tool_approval(
    automation_id: str,
    execution_id: str,
    call_id: str,
    payload: AutomationToolApprovalRequest,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
) -> AutomationExecutionDetailResponse:
    return await resolve_automation_tool_approval(
        db,
        context.workspace.id,
        automation_id,
        execution_id,
        call_id,
        payload.approve,
        context.user,
        context.membership_role,
        settings,
    )


@router.post(
    "/{automation_id}/executions/{execution_id}/form",
    response_model=AutomationExecutionDetailResponse,
)
async def submit_workspace_automation_workflow_form(
    automation_id: str,
    execution_id: str,
    payload: WorkflowFormSubmitRequest,
    context: WorkspaceContextPathDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
) -> AutomationExecutionDetailResponse:
    return await submit_automation_workflow_form(
        db,
        context.workspace.id,
        automation_id,
        execution_id,
        payload,
        context.user,
        context.membership_role,
        settings,
    )


@hooks_router.post(
    "/{hook_id}",
    response_model=AutomationWebhookReceiptResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_automation_webhook(
    hook_id: str,
    request: Request,
    db: DbSessionDep,
    settings: AppSettingsDep,
    x_nexaflow_timestamp: Annotated[
        str | None, Header(alias="X-NexaFlow-Timestamp")
    ] = None,
    x_nexaflow_signature: Annotated[
        str | None, Header(alias="X-NexaFlow-Signature")
    ] = None,
    x_nexaflow_event_id: Annotated[
        str | None, Header(alias="X-NexaFlow-Event-Id")
    ] = None,
    content_length: Annotated[str | None, Header(alias="Content-Length")] = None,
) -> AutomationWebhookReceiptResponse:
    if content_length is not None:
        try:
            if int(content_length) > MAX_WEBHOOK_CONTENT_LENGTH_HEADER:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    "Webhook payload exceeds maximum allowed size.",
                )
        except ValueError:
            pass
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_WEBHOOK_CONTENT_LENGTH_HEADER:
            raise HTTPException(413, "Webhook payload exceeds maximum allowed size.")
        chunks.append(chunk)
    raw_body = b"".join(chunks)
    source_ip = request.client.host if request.client else None
    return await receive_webhook_trigger(
        db,
        hook_id,
        raw_body,
        timestamp_header=x_nexaflow_timestamp,
        signature_header=x_nexaflow_signature,
        event_id_header=x_nexaflow_event_id,
        settings=settings,
        source_ip=source_ip,
    )
