from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.artifacts import GeneratedArtifact
from app.infrastructure.config import Settings
from app.infrastructure.model_utils import utc_now
from app.infrastructure.repositories import artifacts as repository
from app.infrastructure.security import (
    create_artifact_download_token,
    decode_artifact_download_token,
)
from app.infrastructure.session import get_session_factory
from app.shareddomain.artifacts.services import validate_generated_artifact


ARTIFACT_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class GeneratedArtifactLink:
    artifact_id: str
    format: str
    filename: str
    media_type: str
    download_url: str
    expires_at: datetime
    size_bytes: int


def _artifact_link(
    artifact: GeneratedArtifact,
    settings: Settings,
) -> GeneratedArtifactLink:
    token = create_artifact_download_token(artifact.id, artifact.expires_at, settings)
    return GeneratedArtifactLink(
        artifact_id=artifact.id,
        format=artifact.format,
        filename=artifact.filename,
        media_type=artifact.media_type,
        download_url=f"/api/v1/artifacts/{token}",
        expires_at=artifact.expires_at,
        size_bytes=artifact.size_bytes,
    )


async def create_generated_artifact(
    db: AsyncSession,
    settings: Settings,
    *,
    workspace_id: str,
    run_id: str | None,
    idempotency_key: str,
    artifact_format: str,
    filename: str,
    content: bytes,
) -> GeneratedArtifactLink:
    if not workspace_id or not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("Artifact identity is invalid.")
    existing = await repository.get_artifact_by_idempotency_key(
        db,
        workspace_id,
        idempotency_key,
    )
    if existing is not None:
        return _artifact_link(existing, settings)

    media_type = validate_generated_artifact(artifact_format, filename, content)
    now = utc_now()
    artifact = await repository.create_artifact(
        db,
        GeneratedArtifact(
            workspace_id=workspace_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
            format=artifact_format,
            filename=filename,
            media_type=media_type,
            content=content,
            size_bytes=len(content),
            expires_at=now + ARTIFACT_TTL,
            created_at=now,
        ),
    )
    return _artifact_link(artifact, settings)


async def get_generated_artifact(
    db: AsyncSession,
    settings: Settings,
    token: str,
) -> GeneratedArtifact | None:
    artifact_id = decode_artifact_download_token(token, settings)
    if artifact_id is None:
        return None
    return await repository.get_active_artifact(db, artifact_id, utc_now())


async def cleanup_expired_generated_artifacts() -> None:
    async with get_session_factory()() as db:
        await repository.delete_expired_artifacts(db, utc_now())
        await db.commit()
