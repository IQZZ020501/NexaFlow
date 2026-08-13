from typing import Annotated
import json
from collections.abc import AsyncIterator
from enum import IntEnum

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_settings, get_workspace_context_from_path
from app.application.agents import (
    create_agent,
    create_agent_api_credential,
    create_agent_run,
    delete_agent,
    enqueue_prepared_agent_run,
    get_agent,
    get_agent_monitoring,
    get_agent_run_entity,
    get_agent_run_response,
    get_agent_response,
    list_agent_permissions,
    list_agent_run_tool_calls,
    list_agent_api_credentials,
    list_agent_conversation_users,
    list_agent_logs,
    list_agent_runs,
    list_agents,
    prepare_agent_run,
    resolve_workspace_agent_files,
    require_agent_edit,
    resolve_agent_tool_approval,
    revoke_agent_api_credential,
    revoke_agent_permission,
    rotate_agent_api_credential,
    stream_agent_run,
    upload_workspace_agent_files,
    update_agent,
    upsert_agent_permission,
)
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.schemas.agent import (
    AgentApiCredentialCreateRequest,
    AgentApiCredentialCreateResponse,
    AgentApiCredentialListResponse,
    AgentConversationUserListResponse,
    AgentCreateRequest,
    AgentResponse,
    AgentLogListResponse,
    AgentMonitoringResponse,
    AgentPermissionResponse,
    AgentPermissionUpsertRequest,
    AgentRunCreateRequest,
    AgentRunResponse,
    AgentToolCallResponse,
    AgentUploadResponse,
    AgentUpdateRequest,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/agents",
    tags=["agents"],
)


@router.get(
    "/{agent_id}/api-credentials",
    response_model=AgentApiCredentialListResponse,
)
async def list_workspace_agent_api_credentials(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentApiCredentialListResponse:
    return await list_agent_api_credentials(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
    )


@router.post(
    "/{agent_id}/api-credentials",
    response_model=AgentApiCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_agent_api_credential(
    agent_id: str,
    payload: AgentApiCredentialCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentApiCredentialCreateResponse:
    return await create_agent_api_credential(
        db,
        context.workspace.id,
        agent_id,
        payload.name,
        context.user,
        context.membership_role,
    )


@router.delete(
    "/{agent_id}/api-credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workspace_agent_api_credential(
    agent_id: str,
    credential_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await revoke_agent_api_credential(
        db,
        context.workspace.id,
        agent_id,
        credential_id,
        context.user,
        context.membership_role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{agent_id}/api-credentials/{credential_id}/rotate",
    response_model=AgentApiCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_workspace_agent_api_credential(
    agent_id: str,
    credential_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentApiCredentialCreateResponse:
    return await rotate_agent_api_credential(
        db,
        context.workspace.id,
        agent_id,
        credential_id,
        context.user,
        context.membership_role,
    )


@router.get("/{agent_id}/logs", response_model=AgentLogListResponse)
async def list_workspace_agent_logs(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AgentLogListResponse:
    return await list_agent_logs(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
        limit,
        offset,
    )


@router.get(
    "/{agent_id}/conversation-users",
    response_model=AgentConversationUserListResponse,
)
async def list_workspace_agent_conversation_users(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AgentConversationUserListResponse:
    return await list_agent_conversation_users(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
        limit,
        offset,
    )


class AgentMonitoringDays(IntEnum):
    WEEK = 7
    MONTH = 30
    QUARTER = 90


@router.get("/{agent_id}/monitoring", response_model=AgentMonitoringResponse)
async def get_workspace_agent_monitoring(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: AgentMonitoringDays = AgentMonitoringDays.WEEK,
) -> AgentMonitoringResponse:
    return await get_agent_monitoring(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
        days.value,
    )


@router.get("", response_model=list[AgentResponse])
async def list_workspace_agents(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentResponse]:
    return await list_agents(
        db,
        context.workspace.id,
        context.user,
        context.membership_role,
        limit,
        offset,
    )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_agent(
    payload: AgentCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentResponse:
    return await create_agent(
        db,
        context.workspace.id,
        payload,
        context.user,
        context.membership_role,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_workspace_agent(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentResponse:
    agent = await get_agent(db, context.workspace.id, agent_id)
    return await get_agent_response(
        db,
        agent,
        context.user,
        context.membership_role,
    )


@router.get(
    "/{agent_id}/permissions",
    response_model=list[AgentPermissionResponse],
)
async def list_workspace_agent_permissions(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentPermissionResponse]:
    agent = await get_agent(db, context.workspace.id, agent_id)
    require_agent_edit(agent, context.user, context.membership_role)
    return await list_agent_permissions(db, agent, limit, offset)


@router.put(
    "/{agent_id}/permissions/{user_id}",
    response_model=AgentPermissionResponse,
)
async def grant_workspace_agent_permission(
    agent_id: str,
    user_id: str,
    payload: AgentPermissionUpsertRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentPermissionResponse:
    agent = await get_agent(db, context.workspace.id, agent_id)
    require_agent_edit(agent, context.user, context.membership_role)
    return await upsert_agent_permission(
        db,
        agent,
        user_id,
        payload.permission,
        context.user,
    )


@router.delete(
    "/{agent_id}/permissions/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_workspace_agent_permission(
    agent_id: str,
    user_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    agent = await get_agent(db, context.workspace.id, agent_id)
    require_agent_edit(agent, context.user, context.membership_role)
    await revoke_agent_permission(db, agent, user_id, context.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def patch_workspace_agent(
    agent_id: str,
    payload: AgentUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentResponse:
    agent = await get_agent(db, context.workspace.id, agent_id)
    return await update_agent(
        db,
        agent,
        payload,
        context.user,
        context.membership_role,
    )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_agent(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    agent = await get_agent(db, context.workspace.id, agent_id)
    await delete_agent(db, agent, context.user, context.membership_role)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{agent_id}/runs", response_model=list[AgentRunResponse])
async def list_workspace_agent_runs(
    agent_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    conversation_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> list[AgentRunResponse]:
    return await list_agent_runs(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
        limit,
        offset,
        conversation_id,
    )


@router.post(
    "/{agent_id}/uploads",
    response_model=list[AgentUploadResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_workspace_agent_attachments(
    agent_id: str,
    files: Annotated[list[UploadFile], File()],
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AgentUploadResponse]:
    return await upload_workspace_agent_files(
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
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_agent_run(
    agent_id: str,
    payload: AgentRunCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRunResponse:
    return await create_agent_run(
        db,
        context.workspace.id,
        agent_id,
        payload.goal,
        context.user,
        context.membership_role,
        settings,
        conversation_id=payload.conversation_id,
        file_ids=payload.file_ids,
    )


@router.get("/{agent_id}/runs/{run_id}", response_model=AgentRunResponse)
async def get_workspace_agent_run(
    agent_id: str,
    run_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRunResponse:
    return await get_agent_run_response(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        context.user,
        context.membership_role,
    )


@router.get(
    "/{agent_id}/runs/{run_id}/tool-calls",
    response_model=list[AgentToolCallResponse],
)
async def list_workspace_agent_run_tool_calls(
    agent_id: str,
    run_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AgentToolCallResponse]:
    return await list_agent_run_tool_calls(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        context.user,
        context.membership_role,
    )


@router.post("/{agent_id}/runs/stream", response_class=StreamingResponse)
async def stream_workspace_agent_run(
    agent_id: str,
    payload: AgentRunCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    attachment_context = await resolve_workspace_agent_files(
        db,
        context.workspace.id,
        agent_id,
        context.user,
        context.membership_role,
        payload.file_ids,
        settings,
    )
    run, model = await prepare_agent_run(
        db,
        context.workspace.id,
        agent_id,
        payload.goal,
        context.user,
        context.membership_role,
        persist=True,
        conversation_id=payload.conversation_id,
        attachment_context=attachment_context,
    )
    await enqueue_prepared_agent_run(run.id, settings)
    await db.rollback()

    async def encode_events() -> AsyncIterator[bytes]:
        async for event in stream_agent_run(
            db,
            run,
            model,
            context.user,
            context.membership_role,
            settings,
            persist=True,
        ):
            yield (json.dumps(event, ensure_ascii=False) + "\n").encode()

    return StreamingResponse(
        encode_events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/{agent_id}/runs/{run_id}/stream",
    response_class=StreamingResponse,
)
async def reconnect_workspace_agent_run(
    agent_id: str,
    run_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    after: Annotated[int, Query(ge=0)] = 0,
    live_after: Annotated[str, Query(pattern=r"^[0-9]+-[0-9]+$")] = "0-0",
) -> StreamingResponse:
    await get_agent_run_response(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        context.user,
        context.membership_role,
    )
    run = await get_agent_run_entity(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        context.user,
        context.membership_role,
    )
    await db.rollback()

    async def encode_events() -> AsyncIterator[bytes]:
        async for event in stream_agent_run(
            db,
            run,
            None,
            context.user,
            context.membership_role,
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


@router.post(
    "/{agent_id}/runs/{run_id}/tool-calls/{call_id}/approve",
    response_model=AgentRunResponse,
)
async def approve_workspace_agent_tool_call(
    agent_id: str,
    run_id: str,
    call_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRunResponse:
    return await resolve_agent_tool_approval(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        call_id,
        context.user,
        context.membership_role,
        settings,
        approve=True,
    )


@router.post(
    "/{agent_id}/runs/{run_id}/tool-calls/{call_id}/reject",
    response_model=AgentRunResponse,
)
async def reject_workspace_agent_tool_call(
    agent_id: str,
    run_id: str,
    call_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRunResponse:
    return await resolve_agent_tool_approval(
        db,
        context.workspace.id,
        agent_id,
        run_id,
        call_id,
        context.user,
        context.membership_role,
        settings,
        approve=False,
    )
