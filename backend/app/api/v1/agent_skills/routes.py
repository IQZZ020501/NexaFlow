from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_workspace_context_from_path
from app.application.agent_skills import (
    create_agent_skill,
    get_agent_skill,
    list_agent_skill_permissions,
    list_agent_skill_versions,
    list_agent_skills,
    publish_agent_skill,
    revoke_agent_skill_permission,
    update_agent_skill,
    upsert_agent_skill_permission,
)
from app.infra.db.session import get_db
from app.schemas.agent_skills import (
    AgentSkillCreateRequest,
    AgentSkillPermissionResponse,
    AgentSkillPermissionUpsertRequest,
    AgentSkillResponse,
    AgentSkillUpdateRequest,
    AgentSkillVersionResponse,
)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/agent-skills",
    tags=["agent-skills"],
)


@router.get("", response_model=list[AgentSkillResponse])
async def list_workspace_agent_skills(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AgentSkillResponse]:
    return await list_agent_skills(
        db,
        context.workspace.id,
        context.user,
        context.membership_role,
        limit,
        offset,
    )


@router.post("", response_model=AgentSkillResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_agent_skill(
    payload: AgentSkillCreateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentSkillResponse:
    return await create_agent_skill(
        db,
        context.workspace.id,
        payload,
        context.user,
        context.membership_role,
    )


@router.get("/{skill_id}", response_model=AgentSkillResponse)
async def get_workspace_agent_skill(
    skill_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentSkillResponse:
    return await get_agent_skill(
        db,
        context.workspace.id,
        skill_id,
        context.user,
        context.membership_role,
    )


@router.patch("/{skill_id}", response_model=AgentSkillResponse)
async def patch_workspace_agent_skill(
    skill_id: str,
    payload: AgentSkillUpdateRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentSkillResponse:
    return await update_agent_skill(
        db,
        context.workspace.id,
        skill_id,
        payload,
        context.user,
        context.membership_role,
    )


@router.post("/{skill_id}/publish", response_model=AgentSkillVersionResponse)
async def publish_workspace_agent_skill(
    skill_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentSkillVersionResponse:
    return await publish_agent_skill(
        db,
        context.workspace.id,
        skill_id,
        context.user,
        context.membership_role,
    )


@router.get("/{skill_id}/versions", response_model=list[AgentSkillVersionResponse])
async def list_workspace_agent_skill_versions(
    skill_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AgentSkillVersionResponse]:
    return await list_agent_skill_versions(
        db,
        context.workspace.id,
        skill_id,
        context.user,
        context.membership_role,
    )


@router.get(
    "/{skill_id}/permissions", response_model=list[AgentSkillPermissionResponse]
)
async def list_workspace_agent_skill_permissions(
    skill_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AgentSkillPermissionResponse]:
    return await list_agent_skill_permissions(
        db,
        context.workspace.id,
        skill_id,
        context.user,
        context.membership_role,
    )


@router.put(
    "/{skill_id}/permissions/{user_id}",
    response_model=AgentSkillPermissionResponse,
)
async def grant_workspace_agent_skill_permission(
    skill_id: str,
    user_id: str,
    payload: AgentSkillPermissionUpsertRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentSkillPermissionResponse:
    return await upsert_agent_skill_permission(
        db,
        context.workspace.id,
        skill_id,
        user_id,
        payload.permission,
        context.user,
        context.membership_role,
    )


@router.delete(
    "/{skill_id}/permissions/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_workspace_agent_skill_permission(
    skill_id: str,
    user_id: str,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await revoke_agent_skill_permission(
        db,
        context.workspace.id,
        skill_id,
        user_id,
        context.user,
        context.membership_role,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
