from collections.abc import AsyncIterator
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Settings, User, get_db, get_settings, require_password_changed
from app.application.agents import authenticate_agent_api_credential
from app.application.agent_access import (
    PublishedAgentContext,
    get_workspace_published_workflow_context,
)
from app.entities.agents import AgentApiCredential as WorkflowApiCredential
from app.application.workflows import (
    create_external_workflow_run,
    get_external_workflow_run,
    get_public_workflow_profile,
    get_workflow_api_documentation,
    list_external_workflow_runs,
    list_public_workflow_conversations,
    stream_external_workflow_run,
    upload_public_workflow_files,
)
from app.schemas.workflow import (
    ExternalWorkflowRunCreateRequest,
    ExternalWorkflowRunListResponse,
    ExternalWorkflowRunResponse,
    PublicWorkflowConversationListResponse,
    PublicWorkflowProfileResponse,
    WorkflowApiDocumentationResponse,
    WorkflowUploadResponse,
)

_api_key_scheme = HTTPBearer(auto_error=False)

public_router = APIRouter(
    prefix="/public/workflows/{workflow_id}", tags=["public-workflows"]
)
api_router = APIRouter(prefix="/workflow-api/{workflow_id}", tags=["workflow-api"])


async def _encode_events(events: AsyncIterator[dict]) -> AsyncIterator[bytes]:
    async for event in events:
        yield (json.dumps(event, ensure_ascii=False) + "\n").encode()


def _stream_response(events: AsyncIterator[dict]) -> StreamingResponse:
    return StreamingResponse(
        _encode_events(events),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _api_context(
    db: AsyncSession,
    workflow_id: str,
    credentials: HTTPAuthorizationCredentials | None,
) -> tuple[PublishedAgentContext, WorkflowApiCredential]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API credential required.")
    return await authenticate_agent_api_credential(
        db, workflow_id, credentials.credentials, "workflow"
    )


@public_router.get("/profile", response_model=PublicWorkflowProfileResponse)
async def public_workflow_profile(
    workflow_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> PublicWorkflowProfileResponse:
    return await get_public_workflow_profile(db, workflow_id, user)


@public_router.get(
    "/conversations", response_model=PublicWorkflowConversationListResponse
)
async def public_workflow_conversations(
    workflow_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> PublicWorkflowConversationListResponse:
    await get_workspace_published_workflow_context(db, workflow_id, user)
    return await list_public_workflow_conversations(db, workflow_id, user.id)


@public_router.post(
    "/uploads",
    response_model=list[WorkflowUploadResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_public_workflow_attachments(
    workflow_id: str,
    files: Annotated[list[UploadFile], File()],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> list[WorkflowUploadResponse]:
    context = await get_workspace_published_workflow_context(db, workflow_id, user)
    return await upload_public_workflow_files(db, context, user.id, files, settings)


@public_router.get("/runs", response_model=ExternalWorkflowRunListResponse)
async def list_public_workflow_runs(
    workflow_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    conversation_id: Annotated[
        str | None, Query(min_length=1, max_length=36)
    ] = None,
) -> ExternalWorkflowRunListResponse:
    await get_workspace_published_workflow_context(db, workflow_id, user)
    return await list_external_workflow_runs(
        db,
        workflow_id,
        "public",
        user.id,
        limit,
        offset,
        conversation_id,
    )


@public_router.post(
    "/runs",
    response_model=ExternalWorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_public_workflow_run(
    workflow_id: str,
    payload: ExternalWorkflowRunCreateRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> ExternalWorkflowRunResponse:
    context = await get_workspace_published_workflow_context(db, workflow_id, user)
    return await create_external_workflow_run(
        db, context, "public", user.id, payload, context.publisher, settings
    )


@public_router.get("/runs/{run_id}", response_model=ExternalWorkflowRunResponse)
async def get_public_workflow_run(
    workflow_id: str,
    run_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> ExternalWorkflowRunResponse:
    await get_workspace_published_workflow_context(db, workflow_id, user)
    return await get_external_workflow_run(
        db, workflow_id, run_id, "public", user.id
    )


@public_router.get("/runs/{run_id}/stream", response_class=StreamingResponse)
async def stream_public_workflow_run(
    workflow_id: str,
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    await get_workspace_published_workflow_context(db, workflow_id, user)
    await get_external_workflow_run(db, workflow_id, run_id, "public", user.id)
    await db.rollback()
    return _stream_response(stream_external_workflow_run(run_id, settings, after=after))


@api_router.get("/documentation", response_model=WorkflowApiDocumentationResponse)
async def get_api_workflow_documentation(
    workflow_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_api_key_scheme)
    ],
) -> WorkflowApiDocumentationResponse:
    context, _ = await _api_context(db, workflow_id, credentials)
    return await get_workflow_api_documentation(db, context)


@api_router.post(
    "/runs",
    response_model=ExternalWorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_workflow_run(
    workflow_id: str,
    payload: ExternalWorkflowRunCreateRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_api_key_scheme)
    ],
) -> ExternalWorkflowRunResponse:
    context, credential = await _api_context(db, workflow_id, credentials)
    return await create_external_workflow_run(
        db,
        context,
        "api",
        credential.id,
        payload,
        context.publisher,
        settings,
    )


@api_router.get("/runs/{run_id}", response_model=ExternalWorkflowRunResponse)
async def get_api_workflow_run(
    workflow_id: str,
    run_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_api_key_scheme)
    ],
) -> ExternalWorkflowRunResponse:
    _, credential = await _api_context(db, workflow_id, credentials)
    return await get_external_workflow_run(
        db, workflow_id, run_id, "api", credential.id
    )


@api_router.get("/runs/{run_id}/stream", response_class=StreamingResponse)
async def stream_api_workflow_run(
    workflow_id: str,
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_api_key_scheme)
    ],
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    _, credential = await _api_context(db, workflow_id, credentials)
    await get_external_workflow_run(db, workflow_id, run_id, "api", credential.id)
    await db.rollback()
    return _stream_response(stream_external_workflow_run(run_id, settings, after=after))
