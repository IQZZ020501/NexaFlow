"""Project management within the authenticated public Agent chat."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import User, get_db, require_password_changed
from app.api.v1.artifacts.routes import artifact_response
from app.application.projects import chat
from app.schemas.projects import (
    ChatConversationMove,
    ChatConversationResponse,
    ChatProjectArtifactRequest,
    ChatProjectCreate,
    ChatProjectFileListResponse,
    ChatProjectListResponse,
    ChatProjectResponse,
    ChatProjectUpdate,
)

router = APIRouter(prefix="/public/agents/{agent_id}", tags=["public-agent-projects"])
Db = Annotated[AsyncSession, Depends(get_db)]
Actor = Annotated[User, Depends(require_password_changed)]


@router.get("/projects", response_model=ChatProjectListResponse)
async def list_projects(agent_id: str, db: Db, actor: Actor):
    return ChatProjectListResponse(items=await chat.list_projects(db, agent_id, actor))


@router.post("/projects", response_model=ChatProjectResponse, status_code=201)
async def create_project(
    agent_id: str, payload: ChatProjectCreate, db: Db, actor: Actor
):
    return await chat.create_project(db, agent_id, actor, payload)


@router.put("/projects/{project_id}", response_model=ChatProjectResponse)
async def update_project(
    agent_id: str, project_id: str, payload: ChatProjectUpdate, db: Db, actor: Actor
):
    return await chat.update_project(db, agent_id, actor, project_id, payload)


@router.delete("/projects/{project_id}", status_code=204)
async def dissolve_project(agent_id: str, project_id: str, db: Db, actor: Actor):
    await chat.dissolve_project(db, agent_id, actor, project_id)


@router.post(
    "/projects/{project_id}/conversations",
    response_model=ChatConversationResponse,
    status_code=201,
)
async def create_project_conversation(
    agent_id: str, project_id: str, db: Db, actor: Actor
):
    conversation = await chat.create_conversation(db, agent_id, actor, project_id)
    return ChatConversationResponse(
        conversation_id=conversation.conversation_id, project_id=conversation.project_id
    )


@router.patch(
    "/conversations/{conversation_id}/project", response_model=ChatConversationResponse
)
async def move_conversation(
    agent_id: str,
    conversation_id: str,
    payload: ChatConversationMove,
    db: Db,
    actor: Actor,
):
    conversation = await chat.move_conversation(
        db, agent_id, actor, conversation_id, payload.project_id
    )
    return ChatConversationResponse(
        conversation_id=conversation.conversation_id, project_id=conversation.project_id
    )


@router.get("/projects/{project_id}/files", response_model=ChatProjectFileListResponse)
async def list_files(agent_id: str, project_id: str, db: Db, actor: Actor):
    return ChatProjectFileListResponse(
        items=await chat.list_files(db, agent_id, actor, project_id)
    )


@router.post(
    "/projects/{project_id}/files",
    response_model=ChatProjectFileListResponse,
    status_code=201,
)
async def upload_files(
    agent_id: str,
    project_id: str,
    db: Db,
    actor: Actor,
    files: Annotated[list[UploadFile], File()],
):
    if not 1 <= len(files) <= 64:
        raise HTTPException(
            422, "Chat project files exceed their limits or contain invalid paths."
        )
    uploads = []
    total = 0
    for file in files:
        content = await file.read(5 * 1024 * 1024 + 1)
        total += len(content)
        if len(content) > 5 * 1024 * 1024 or total > 64 * 1024 * 1024:
            raise HTTPException(
                422, "Chat project files exceed their limits or contain invalid paths."
            )
        uploads.append((file.filename or "", content))
    return ChatProjectFileListResponse(
        items=await chat.upload_files(db, agent_id, actor, project_id, uploads)
    )


@router.post(
    "/projects/{project_id}/artifacts",
    response_model=ChatProjectFileListResponse,
    status_code=201,
)
async def save_artifact(
    agent_id: str,
    project_id: str,
    payload: ChatProjectArtifactRequest,
    db: Db,
    actor: Actor,
):
    return ChatProjectFileListResponse(
        items=await chat.save_artifact(
            db, agent_id, actor, project_id, payload.artifact_id
        )
    )


@router.get(
    "/projects/{project_id}/files/{version_id}/content", response_class=Response
)
async def download_file(
    agent_id: str, project_id: str, version_id: str, db: Db, actor: Actor
):
    return artifact_response(
        await chat.read_file(db, agent_id, actor, project_id, version_id)
    )


@router.delete("/projects/{project_id}/files/{version_id}", status_code=204)
async def delete_file(
    agent_id: str, project_id: str, version_id: str, db: Db, actor: Actor
):
    await chat.delete_file(db, agent_id, actor, project_id, version_id)
