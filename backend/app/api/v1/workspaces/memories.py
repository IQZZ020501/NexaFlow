"""Personal memory shared across a user's Agents in one workspace."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, get_workspace_context_from_path
from app.application import memories
from app.schemas.memories import (
    MemoryPreferencesRequest,
    MemoryProfileResponse,
    MemoryProjectListResponse,
    MemoryWriteRequest,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/memories", tags=["user-memories"])
Db = Annotated[AsyncSession, Depends(get_db)]
Context = Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)]


@router.get("", response_model=MemoryProfileResponse)
async def get_profile(context: Context, db: Db):
    return await memories.get_memory_profile(db, context.workspace.id, context.user)


@router.get("/projects", response_model=MemoryProjectListResponse)
async def list_projects(context: Context, db: Db):
    return {
        "items": await memories.get_memory_projects(
            db, context.workspace.id, context.user
        )
    }


@router.put("/preferences", response_model=MemoryProfileResponse)
async def set_preferences(
    payload: MemoryPreferencesRequest, context: Context, db: Db
):
    return await memories.update_preferences(
        db, context.workspace.id, context.user, payload
    )


@router.post("", response_model=MemoryProfileResponse, status_code=201)
async def create_memory(payload: MemoryWriteRequest, context: Context, db: Db):
    return await memories.write_memory(db, context.workspace.id, context.user, payload)


@router.put("/{memory_id}", response_model=MemoryProfileResponse)
async def edit_memory(
    memory_id: str, payload: MemoryWriteRequest, context: Context, db: Db
):
    return await memories.write_memory(
        db, context.workspace.id, context.user, payload, memory_id
    )


@router.delete("", status_code=204)
async def clear_memories(context: Context, db: Db):
    await memories.clear_memories(db, context.workspace.id, context.user)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, context: Context, db: Db):
    await memories.delete_memory(db, context.workspace.id, context.user, memory_id)
