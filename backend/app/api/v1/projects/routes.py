from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_workspace_context_from_path
from app.application.projects import service
from app.infra.db.session import get_db
from app.schemas.projects import (
    ProjectCreateRequest,
    ProjectFileDeleteRequest,
    ProjectFileRenameRequest,
    ProjectFileResponse,
    ProjectResponse,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/projects", tags=["projects"])
Context = Annotated[WorkspaceContext, Depends(get_workspace_context_from_path)]
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    context: Context,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await service.list_projects(
        db, context.workspace.id, context.user.id, limit, offset
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(payload: ProjectCreateRequest, context: Context, db: Database):
    return await service.create_project(
        db, context.workspace.id, context.user.id, payload.name
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, context: Context, db: Database):
    return ProjectResponse.model_validate(
        await service.require_project(
            db, context.workspace.id, project_id, context.user.id
        )
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def rename_project(
    project_id: str, payload: ProjectCreateRequest, context: Context, db: Database
):
    return await service.rename_project(
        db, context.workspace.id, project_id, context.user.id, payload.name
    )


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, context: Context, db: Database):
    await service.delete_project(db, context.workspace.id, project_id, context.user.id)
    return Response(status_code=204)


@router.get("/{project_id}/files", response_model=list[ProjectFileResponse])
async def list_files(project_id: str, context: Context, db: Database):
    return await service.list_files(
        db, context.workspace.id, project_id, context.user.id
    )


@router.post("/{project_id}/files", response_model=ProjectFileResponse)
async def upload_file(
    project_id: str,
    file: UploadFile,
    context: Context,
    db: Database,
    path: Annotated[str, Form(min_length=1, max_length=512)],
    role: Annotated[Literal["source", "work"], Form()],
    expected_version_id: Annotated[str | None, Form(max_length=36)] = None,
):
    content = await file.read(5 * 1024 * 1024 + 1)
    if not 0 < len(content) <= 5 * 1024 * 1024:
        raise HTTPException(422, "Each project file must be between 1 byte and 5 MiB.")
    return await service.put_file(
        db,
        context.workspace.id,
        project_id,
        context.user.id,
        path,
        role,
        content,
        expected_version_id,
    )


@router.delete("/{project_id}/files", response_model=ProjectFileResponse)
async def delete_file(
    project_id: str, payload: ProjectFileDeleteRequest, context: Context, db: Database
):
    return await service.delete_file(
        db,
        context.workspace.id,
        project_id,
        context.user.id,
        payload.path,
        payload.expected_version_id,
    )


@router.post("/{project_id}/files/rename", response_model=ProjectFileResponse)
async def rename_file(
    project_id: str, payload: ProjectFileRenameRequest, context: Context, db: Database
):
    return await service.rename_file(
        db,
        context.workspace.id,
        project_id,
        context.user.id,
        payload.path,
        payload.new_path,
        payload.expected_version_id,
    )


@router.get("/{project_id}/versions", response_model=list[ProjectFileResponse])
async def list_versions(
    project_id: str,
    context: Context,
    db: Database,
    path: Annotated[str, Query(min_length=1, max_length=512)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await service.list_versions(
        db, context.workspace.id, project_id, context.user.id, path, limit, offset
    )


@router.get("/{project_id}/versions/{version_id}/content", response_class=Response)
async def download_file(
    project_id: str, version_id: str, context: Context, db: Database
):
    file = await service.get_file(
        db, context.workspace.id, project_id, context.user.id, version_id
    )
    return Response(
        content=file.content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(file.path.rsplit("/", 1)[-1], safe=""),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "ETag": f'"{file.content_hash}"',
        },
    )
