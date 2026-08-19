from collections.abc import AsyncIterator
import json
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_settings, require_password_changed
from app.application.agents import (
    authenticate_agent_api_credential,
    create_external_agent_run,
    external_run_to_response,
    get_external_agent_run,
    get_public_agent_profile,
    get_workspace_published_agent_context,
    list_external_agent_runs,
    list_external_agent_run_tool_calls,
    list_public_agent_conversations,
    regenerate_external_agent_run,
    resolve_external_agent_tool_approval,
    set_external_agent_run_feedback,
    stream_external_agent_run,
    upload_public_agent_files,
)
from app.application.agent_access import PublishedAgentContext
from app.entities.agents import AgentApiCredential
from app.entities.user import User
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.schemas.agent import (
    AgentApiDocumentationResponse,
    AgentUploadResponse,
    AgentToolCallResponse,
    ExternalAgentRunCreateRequest,
    ExternalAgentRunListResponse,
    ExternalAgentRunResponse,
    PublicAgentConversationListResponse,
    PublicAgentProfileResponse,
    PublicAgentRunCreateRequest,
    RunFeedbackRequest,
)

_api_key_scheme = HTTPBearer(auto_error=False)

public_router = APIRouter(prefix="/public/agents/{agent_id}", tags=["public-agents"])
api_router = APIRouter(prefix="/agent-api/{agent_id}", tags=["agent-api"])

async def _encode_events(events: AsyncIterator[dict]) -> AsyncIterator[bytes]:
    async for event in events:
        yield (json.dumps(event, ensure_ascii=False) + "\n").encode()


def _stream_response(events: AsyncIterator[dict]) -> StreamingResponse:
    return StreamingResponse(
        _encode_events(events),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@public_router.get("/profile", response_model=PublicAgentProfileResponse)
async def public_agent_profile(
    agent_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> PublicAgentProfileResponse:
    return await get_public_agent_profile(db, agent_id, user)


@public_router.get(
    "/conversations",
    response_model=PublicAgentConversationListResponse,
)
async def public_agent_conversations(
    agent_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> PublicAgentConversationListResponse:
    await get_workspace_published_agent_context(db, agent_id, user)
    return await list_public_agent_conversations(db, agent_id, user.id)


@public_router.post(
    "/uploads",
    response_model=list[AgentUploadResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_public_agent_attachments(
    agent_id: str,
    files: Annotated[list[UploadFile], File()],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> list[AgentUploadResponse]:
    context = await get_workspace_published_agent_context(db, agent_id, user)
    return await upload_public_agent_files(db, context, user.id, files, settings)


@public_router.get("/runs", response_model=ExternalAgentRunListResponse)
async def list_public_agent_runs(
    agent_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    conversation_id: Annotated[
        str | None, Query(min_length=1, max_length=36)
    ] = None,
) -> ExternalAgentRunListResponse:
    await get_workspace_published_agent_context(db, agent_id, user)
    return await list_external_agent_runs(
        db,
        agent_id,
        "public",
        user.id,
        limit,
        offset,
        conversation_id,
    )


@public_router.post(
    "/runs",
    response_model=ExternalAgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_public_agent_run(
    agent_id: str,
    payload: PublicAgentRunCreateRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> ExternalAgentRunResponse:
    context = await get_workspace_published_agent_context(db, agent_id, user)
    return await create_external_agent_run(
        db,
        context,
        "public",
        user.id,
        payload.goal,
        settings,
        payload.conversation_id,
        payload.file_ids,
    )


@public_router.get("/runs/{run_id}", response_model=ExternalAgentRunResponse)
async def get_public_agent_run(
    agent_id: str,
    run_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> ExternalAgentRunResponse:
    await get_workspace_published_agent_context(db, agent_id, user)
    run = await get_external_agent_run(
        db,
        agent_id,
        run_id,
        "public",
        user.id,
    )
    return external_run_to_response(run)


@public_router.post(
    "/runs/{run_id}/regenerate",
    response_model=ExternalAgentRunResponse,
)
async def regenerate_public_agent_run(
    agent_id: str,
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> ExternalAgentRunResponse:
    context = await get_workspace_published_agent_context(db, agent_id, user)
    return await regenerate_external_agent_run(
        db,
        context,
        run_id,
        "public",
        user.id,
        settings,
    )


@public_router.post(
    "/runs/{run_id}/feedback",
    response_model=ExternalAgentRunResponse,
)
async def set_public_agent_run_feedback(
    agent_id: str,
    run_id: str,
    payload: RunFeedbackRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> ExternalAgentRunResponse:
    await get_workspace_published_agent_context(db, agent_id, user)
    return await set_external_agent_run_feedback(
        db,
        agent_id,
        run_id,
        "public",
        user.id,
        payload.value,
    )


@public_router.get("/runs/{run_id}/stream", response_class=StreamingResponse)
async def stream_public_agent_run(
    agent_id: str,
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
    after: Annotated[int, Query(ge=0)] = 0,
    live_after: Annotated[str, Query(pattern=r"^[0-9]+-[0-9]+$")] = "0-0",
) -> StreamingResponse:
    context = await get_workspace_published_agent_context(db, agent_id, user)
    run = await get_external_agent_run(db, agent_id, run_id, "public", user.id)
    await db.rollback()
    return _stream_response(
        stream_external_agent_run(
            db,
            context,
            run,
            settings,
            after=after,
            live_after=live_after,
        )
    )


@public_router.get(
    "/runs/{run_id}/tool-calls",
    response_model=list[AgentToolCallResponse],
)
async def list_public_agent_run_tool_calls(
    agent_id: str,
    run_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> list[AgentToolCallResponse]:
    await get_workspace_published_agent_context(db, agent_id, user)
    return await list_external_agent_run_tool_calls(
        db,
        agent_id,
        run_id,
        "public",
        user.id,
    )


@public_router.post(
    "/runs/{run_id}/tool-calls/{call_id}/approve",
    response_model=ExternalAgentRunResponse,
)
async def approve_public_agent_run_tool_call(
    agent_id: str,
    run_id: str,
    call_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> ExternalAgentRunResponse:
    await get_workspace_published_agent_context(db, agent_id, user)
    return await resolve_external_agent_tool_approval(
        db,
        agent_id,
        run_id,
        call_id,
        "public",
        user,
        settings,
        approve=True,
    )


@public_router.post(
    "/runs/{run_id}/tool-calls/{call_id}/reject",
    response_model=ExternalAgentRunResponse,
)
async def reject_public_agent_run_tool_call(
    agent_id: str,
    run_id: str,
    call_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_password_changed)],
) -> ExternalAgentRunResponse:
    await get_workspace_published_agent_context(db, agent_id, user)
    return await resolve_external_agent_tool_approval(
        db,
        agent_id,
        run_id,
        call_id,
        "public",
        user,
        settings,
        approve=False,
    )


async def _api_context(
    db: AsyncSession,
    agent_id: str,
    credentials: HTTPAuthorizationCredentials | None,
) -> tuple[PublishedAgentContext, AgentApiCredential]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API credential required.")
    return await authenticate_agent_api_credential(
        db, agent_id, credentials.credentials
    )


@api_router.get("/documentation", response_model=AgentApiDocumentationResponse)
async def get_api_agent_documentation(
    agent_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_api_key_scheme)
    ],
) -> AgentApiDocumentationResponse:
    context, _ = await _api_context(db, agent_id, credentials)
    if context.publication is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Published agent not found.")
    return AgentApiDocumentationResponse(
        agent_id=context.agent.id,
        agent_name=context.publication.name,
        base_path=f"/api/v1/agent-api/{context.agent.id}",
    )


@api_router.post(
    "/runs",
    response_model=ExternalAgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_agent_run(
    agent_id: str,
    payload: ExternalAgentRunCreateRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_api_key_scheme)
    ],
) -> ExternalAgentRunResponse:
    context, credential = await _api_context(db, agent_id, credentials)
    return await create_external_agent_run(
        db,
        context,
        "api",
        credential.id,
        payload.goal,
        settings,
        payload.conversation_id,
    )


@api_router.get("/runs/{run_id}", response_model=ExternalAgentRunResponse)
async def get_api_agent_run(
    agent_id: str,
    run_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_api_key_scheme)
    ],
) -> ExternalAgentRunResponse:
    _, credential = await _api_context(db, agent_id, credentials)
    run = await get_external_agent_run(
        db, agent_id, run_id, "api", credential.id
    )
    return external_run_to_response(run)


@api_router.get("/runs/{run_id}/stream", response_class=StreamingResponse)
async def stream_api_agent_run(
    agent_id: str,
    run_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_api_key_scheme)
    ],
    after: Annotated[int, Query(ge=0)] = 0,
    live_after: Annotated[str, Query(pattern=r"^[0-9]+-[0-9]+$")] = "0-0",
) -> StreamingResponse:
    context, credential = await _api_context(db, agent_id, credentials)
    run = await get_external_agent_run(db, agent_id, run_id, "api", credential.id)
    await db.rollback()
    return _stream_response(
        stream_external_agent_run(
            db,
            context,
            run,
            settings,
            after=after,
            live_after=live_after,
        )
    )
