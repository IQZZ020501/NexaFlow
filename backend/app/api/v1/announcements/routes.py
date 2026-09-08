from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    WorkspaceContext,
    get_settings,
    get_workspace_context_from_path,
    require_global_admin,
    require_password_changed,
    require_workspace_path_role,
)
from app.application.announcements import (
    archive_announcement,
    create_announcement,
    get_unread_message_count,
    list_announcements,
    list_messages,
    mark_all_messages_read,
    mark_message_read,
    publish_announcement,
    update_announcement,
)
from app.application.workspaces.service import build_workspace_context
from app.entities.identity.user import User
from app.infra.announcements.live_stream import AnnouncementLiveStreamReader
from app.infra.config.settings import Settings
from app.infra.db.session import get_db
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


async def _validate_optional_workspace(
    db: AsyncSession,
    user: User,
    workspace_id: str | None,
) -> None:
    if workspace_id is not None:
        await build_workspace_context(db, user, workspace_id)


@message_router.get("", response_model=list[AnnouncementMessageResponse])
async def list_current_messages(
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AnnouncementMessageResponse]:
    await _validate_optional_workspace(db, user, workspace_id)
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
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
) -> MessageUnreadCountResponse:
    await _validate_optional_workspace(db, user, workspace_id)
    return MessageUnreadCountResponse(
        count=await get_unread_message_count(
            db,
            user=user,
            workspace_id=workspace_id,
        )
    )


@message_router.get("/stream", response_class=EventSourceResponse)
async def stream_current_messages(
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
    global_after: Annotated[str | None, Query(max_length=64)] = None,
    workspace_after: Annotated[str | None, Query(max_length=64)] = None,
) -> AsyncIterable[ServerSentEvent]:
    await _validate_optional_workspace(db, user, workspace_id)
    await db.close()
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    reader = AnnouncementLiveStreamReader(settings, workspace_id=workspace_id)
    current_global_after = global_after
    current_workspace_after = workspace_after
    try:
        while True:
            entries = await reader.read(
                global_after=current_global_after,
                workspace_after=current_workspace_after,
            )
            if not reader.available:
                yield ServerSentEvent(
                    event="unavailable",
                    data={"type": "unavailable"},
                    retry=5000,
                )
                return
            if not entries:
                yield ServerSentEvent(comment="keep-alive")
                continue
            for stream_name, entry_id, event in entries:
                if stream_name.endswith(":global"):
                    current_global_after = entry_id
                    stream_scope = "global"
                else:
                    current_workspace_after = entry_id
                    stream_scope = "workspace"
                yield ServerSentEvent(
                    event="announcement",
                    id=f"{stream_scope}:{entry_id}",
                    data=event,
                )
    finally:
        await reader.close()


@message_router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_current_messages_read(
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
) -> Response:
    await _validate_optional_workspace(db, user, workspace_id)
    await mark_all_messages_read(
        db,
        user=user,
        workspace_id=workspace_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@message_router.post("/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_current_message_read(
    message_id: str,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: Annotated[str | None, Query(max_length=36)] = None,
) -> Response:
    await _validate_optional_workspace(db, user, workspace_id)
    await mark_message_read(
        db,
        user=user,
        workspace_id=workspace_id,
        announcement_id=message_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@global_admin_router.get("", response_model=list[AnnouncementResponse])
async def list_global_announcements(
    _: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    actor: Annotated[User, Depends(require_global_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    actor: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    actor: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    actor: Annotated[User, Depends(require_global_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
    context: Annotated[WorkspaceContext, Depends(require_workspace_path_role({"admin"}))],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnnouncementResponse:
    return await archive_announcement(
        db,
        scope_type="workspace",
        workspace_id=context.workspace.id,
        announcement_id=announcement_id,
        actor=context.user,
        settings=settings,
    )
