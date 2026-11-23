from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_settings, require_password_changed
from app.application.artifacts.service import (
    get_authorized_artifact,
    get_generated_artifact,
)
from app.entities.identity.user import User
from app.infra.config.settings import Settings
from app.infra.db.session import get_db
from app.schemas.artifacts import ArtifactDownloadRequest

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


async def _download_response(
    token: str,
    settings: Settings,
    db: AsyncSession,
) -> Response:
    artifact = await get_generated_artifact(db, settings, token)
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found.")

    return artifact_response(artifact)


def artifact_response(artifact) -> Response:
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Disposition": (
            "attachment; filename*=UTF-8''" + quote(artifact.filename, safe="")
        ),
    }
    try:
        headers["X-NexaFlow-Artifact-ID"] = str(UUID(artifact.id))
        if artifact.run_id:
            headers["X-NexaFlow-Run-ID"] = str(UUID(artifact.run_id))
    except ValueError:
        pass
    if artifact.content_hash:
        headers["ETag"] = f'"{artifact.content_hash}"'
    if artifact.inspection.get("status") == "passed":
        headers["X-NexaFlow-File-Check"] = artifact.inspection["validator"]
    if artifact.format in {"html", "htm", "xhtml", "svg"}:
        headers["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; style-src 'unsafe-inline'; "
            "img-src data:; font-src data:; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'"
        )
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers=headers,
    )


@router.get("/{artifact_id}/content", response_class=Response)
async def download_authorized_artifact(
    artifact_id: str,
    user: Annotated[User, Depends(require_password_changed)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    return artifact_response(await get_authorized_artifact(db, artifact_id, user))


@router.post("/download", response_class=Response)
async def download_generated_artifact_by_body(
    payload: ArtifactDownloadRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    return await _download_response(payload.token, settings, db)


@router.get("/{token}", response_class=Response)
async def download_generated_artifact(
    token: str,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    return await _download_response(token, settings, db)


@router.get("/{token}/preview", response_class=Response)
async def preview_generated_image(
    token: str,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    artifact = await get_generated_artifact(db, settings, token)
    if artifact is None or artifact.format != "png" or artifact.media_type != "image/png":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found.")
    return Response(
        content=artifact.content,
        media_type="image/png",
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "private, no-store",
        },
    )
