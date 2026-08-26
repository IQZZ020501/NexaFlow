from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_settings
from app.application.artifacts import get_generated_artifact
from app.infrastructure.config import Settings
from app.infrastructure.session import get_db
from app.schemas.artifact import ArtifactDownloadRequest


router = APIRouter(prefix="/artifacts", tags=["artifacts"])


async def _download_response(
    token: str,
    settings: Settings,
    db: AsyncSession,
) -> Response:
    artifact = await get_generated_artifact(db, settings, token)
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found.")

    headers = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Disposition": (
            "attachment; filename*=UTF-8''" + quote(artifact.filename, safe="")
        ),
    }
    if artifact.format == "html":
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
