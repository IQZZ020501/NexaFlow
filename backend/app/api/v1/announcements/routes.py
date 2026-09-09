from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.deps import (
    AppSettingsDep,
    CurrentUserDep,
    DbSessionDep,
    GlobalAdminDep,
    WorkspaceAdminContextDep,
)
from app.application.announcements import (
    archive_announcement,
    create_announcement,
    get_message_summary,
    list_announcements,
    list_messages,
    mark_all_messages_read,
    mark_message_read,
    publish_announcement,
    stream_message_updates,
    update_announcement,
    validate_message_workspace_access,
)
from app.schemas.announcements import (
    AnnouncementCreateRequest,
    AnnouncementMessageResponse,
    AnnouncementResponse,
    AnnouncementUpdateRequest,
    MessageUnreadCountResponse,
)

message_router = APIRouter(prefix="/messages", tags=["messages"])
global_admin_router = APIRouter(
    prefix="/admin/announcements",
    tags=["announcements"],
)
workspace_router = APIRouter(
    prefix="/workspaces/{workspace_id}/announcements",
    tags=["announcements"],
)


@message_router.get("", response_model=list[AnnouncementMessageResponse])
async def list_current_messages(
    user: CurrentUserDep,
    db: DbSessionDep,
    response: Response,
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AnnouncementMessageResponse]:
    await validate_message_workspace_access(db, user, workspace_id)
    messages, total = await list_messages(
        db,
        user=user,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return messages


@message_router.get("/unread-count", response_model=MessageUnreadCountResponse)
async def read_unread_message_count(
    user: CurrentUserDep,
    db: DbSessionDep,
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
) -> MessageUnreadCountResponse:
    await validate_message_workspace_access(db, user, workspace_id)
    count, next_expiration_at = await get_message_summary(
        db,
        user=user,
        workspace_id=workspace_id,
    )
    return MessageUnreadCountResponse(
        count=count,
        next_expiration_at=next_expiration_at,
    )


@message_router.get("/stream", response_class=EventSourceResponse)
async def stream_current_messages(
    user: CurrentUserDep,
    db: DbSessionDep,
    settings: AppSettingsDep,
    response: Response,
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
    global_after: Annotated[str | None, Query(max_length=64)] = None,
    workspace_after: Annotated[str | None, Query(max_length=64)] = None,
) -> AsyncIterable[ServerSentEvent]:
    await validate_message_workspace_access(db, user, workspace_id)
    await db.close()
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    async for update in stream_message_updates(
        settings,
        workspace_id=workspace_id,
        global_after=global_after,
        workspace_after=workspace_after,
    ):
        if update.kind == "keep-alive":
            yield ServerSentEvent(comment="keep-alive")
        elif update.kind == "unavailable":
            yield ServerSentEvent(
                event="unavailable",
                data=update.data,
                retry=5000,
            )
        else:
            yield ServerSentEvent(
                event="announcement",
                id=update.event_id,
                data=update.data,
            )


@message_router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_current_messages_read(
    user: CurrentUserDep,
    db: DbSessionDep,
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
) -> Response:
    await validate_message_workspace_access(db, user, workspace_id)
    await mark_all_messages_read(
        db,
        user=user,
        workspace_id=workspace_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@message_router.post("/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_current_message_read(
    message_id: str,
    user: CurrentUserDep,
    db: DbSessionDep,
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
) -> Response:
    await validate_message_workspace_access(db, user, workspace_id)
    await mark_message_read(
        db,
        user=user,
        workspace_id=workspace_id,
        announcement_id=message_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@global_admin_router.get("", response_model=list[AnnouncementResponse])
async def list_global_announcements(
    _: GlobalAdminDep,
    db: DbSessionDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AnnouncementResponse]:
    announcements, total = await list_announcements(
        db,
        scope_type="global",
        workspace_id=None,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return announcements


@global_admin_router.post(
    "",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_global_announcement(
    payload: AnnouncementCreateRequest,
    actor: GlobalAdminDep,
    db: DbSessionDep,
) -> AnnouncementResponse:
    return await create_announcement(
        db,
        scope_type="global",
        workspace_id=None,
        actor=actor,
        payload=payload,
    )


@global_admin_router.patch("/{announcement_id}", response_model=AnnouncementResponse)
async def update_global_announcement(
    announcement_id: str,
    payload: AnnouncementUpdateRequest,
    actor: GlobalAdminDep,
    settings: AppSettingsDep,
    db: DbSessionDep,
) -> AnnouncementResponse:
    return await update_announcement(
        db,
        scope_type="global",
        workspace_id=None,
        announcement_id=announcement_id,
        actor=actor,
        payload=payload,
        settings=settings,
    )


@global_admin_router.post("/{announcement_id}/publish", response_model=AnnouncementResponse)
async def publish_global_announcement(
    announcement_id: str,
    actor: GlobalAdminDep,
    settings: AppSettingsDep,
    db: DbSessionDep,
) -> AnnouncementResponse:
    return await publish_announcement(
        db,
        scope_type="global",
        workspace_id=None,
        announcement_id=announcement_id,
        actor=actor,
        settings=settings,
    )


@global_admin_router.post("/{announcement_id}/archive", response_model=AnnouncementResponse)
async def archive_global_announcement(
    announcement_id: str,
    actor: GlobalAdminDep,
    settings: AppSettingsDep,
    db: DbSessionDep,
) -> AnnouncementResponse:
    return await archive_announcement(
        db,
        scope_type="global",
        workspace_id=None,
        announcement_id=announcement_id,
        actor=actor,
        settings=settings,
    )


@workspace_router.get("", response_model=list[AnnouncementResponse])
async def list_workspace_announcements(
    context: WorkspaceAdminContextDep,
    db: DbSessionDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AnnouncementResponse]:
    announcements, total = await list_announcements(
        db,
        scope_type="workspace",
        workspace_id=context.workspace.id,
        limit=limit,
        offset=offset,
    )
    response.headers["X-Total-Count"] = str(total)
    return announcements


@workspace_router.post("", response_model=AnnouncementResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_announcement(
    payload: AnnouncementCreateRequest,
    context: WorkspaceAdminContextDep,
    db: DbSessionDep,
) -> AnnouncementResponse:
    return await create_announcement(
        db,
        scope_type="workspace",
        workspace_id=context.workspace.id,
        actor=context.user,
        payload=payload,
    )


@workspace_router.patch("/{announcement_id}", response_model=AnnouncementResponse)
async def update_workspace_announcement(
    announcement_id: str,
    payload: AnnouncementUpdateRequest,
    context: WorkspaceAdminContextDep,
    settings: AppSettingsDep,
    db: DbSessionDep,
) -> AnnouncementResponse:
    return await update_announcement(
        db,
        scope_type="workspace",
        workspace_id=context.workspace.id,
        announcement_id=announcement_id,
        actor=context.user,
        payload=payload,
        settings=settings,
    )


@workspace_router.post("/{announcement_id}/publish", response_model=AnnouncementResponse)
async def publish_workspace_announcement(
    announcement_id: str,
    context: WorkspaceAdminContextDep,
    settings: AppSettingsDep,
    db: DbSessionDep,
) -> AnnouncementResponse:
    return await publish_announcement(
        db,
        scope_type="workspace",
        workspace_id=context.workspace.id,
        announcement_id=announcement_id,
        actor=context.user,
        settings=settings,
    )


@workspace_router.post("/{announcement_id}/archive", response_model=AnnouncementResponse)
async def archive_workspace_announcement(
    announcement_id: str,
    context: WorkspaceAdminContextDep,
    settings: AppSettingsDep,
    db: DbSessionDep,
) -> AnnouncementResponse:
    return await archive_announcement(
        db,
        scope_type="workspace",
        workspace_id=context.workspace.id,
        announcement_id=announcement_id,
        actor=context.user,
        settings=settings,
    )
